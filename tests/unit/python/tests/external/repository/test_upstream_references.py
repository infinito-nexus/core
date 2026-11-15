"""The external upstream check skips a rate-limited item and fails everything else.

Runs the external suite's own test method with ``requests.get`` mocked, so no
request leaves the process.
"""

from __future__ import annotations

import os
import unittest
import unittest.mock as mock

import requests

from tests.external.repository import test_upstream_references as suite
from utils.upstream import trackers
from utils.upstream.directive import Directive, classify

GH = "https://github.com"
LIMITED_URL = f"{GH}/owner/repo/issues/7"
CLOSED_URL = f"{GH}/owner/repo/pull/8"
LIMITED = Directive("scripts/lint/action.sh", 12, LIMITED_URL)
CLOSED = Directive("compose/registry-cache/proxy.conf", 15, CLOSED_URL)
DATE = "2026-10-20T10:00:00Z"
RESET_EPOCH = "1800000000"
RESET_WORDS = "at 2027-01-15T08:00:00+00:00"


class _Response:
    """Stand-in for the ``requests.Response`` the adapters read."""

    def __init__(self, status_code: int, body: object, headers: dict[str, str]):
        self.status_code = status_code
        self.headers = headers
        self._body = body

    def json(self) -> object:
        return self._body


EXHAUSTED = _Response(
    403, None, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": RESET_EPOCH}
)
MERGED = _Response(
    200,
    {"state": "closed", "closed_at": DATE, "pull_request": {"merged_at": DATE}},
    {},
)


def _api(directive: Directive) -> str:
    """The API URL the suite asks for *directive*'s item.

    Args:
        directive: a directive naming an accepted URL.
    """
    reference = classify(directive.text)
    assert reference is not None
    return trackers.api_url(reference)


class TestRateLimitSkip(unittest.TestCase):
    def setUp(self) -> None:
        self.warning = mock.Mock()
        for patcher in (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(trackers.time, "sleep"),
            mock.patch.object(suite, "resolve_max_fetch_workers", return_value=1),
            mock.patch.object(suite, "warning", self.warning),
            mock.patch.object(suite, "error"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, directives: list[Directive], get: object) -> unittest.TestResult:
        result = unittest.TestResult()
        case = suite.TestUpstreamReferences("test_every_referenced_item_is_still_open")
        with (
            mock.patch.object(suite, "repository_directives", return_value=directives),
            mock.patch.object(trackers.requests, "get", side_effect=get),
        ):
            case.run(result)
        return result

    def _routed(self, answers: dict[str, _Response]) -> object:
        def get(url: str, **_kwargs: object) -> _Response:
            return answers[url]

        return get

    def test_a_rate_limited_item_skips_naming_url_line_reset_and_token(self) -> None:
        result = self._run([LIMITED], self._routed({_api(LIMITED): EXHAUSTED}))

        self.assertEqual((result.failures, result.errors), ([], []))
        self.assertEqual(len(result.skipped), 1)
        reason = result.skipped[0][1]
        for expected in (
            LIMITED_URL,
            f"{LIMITED.path}:{LIMITED.line}",
            RESET_WORDS,
            "GITHUB_TOKEN",
            "GH_TOKEN",
        ):
            self.assertIn(expected, reason)
        self.warning.assert_called_once()

    def test_a_closed_item_still_fails_beside_a_rate_limited_one(self) -> None:
        result = self._run(
            [LIMITED, CLOSED],
            self._routed({_api(LIMITED): EXHAUSTED, _api(CLOSED): MERGED}),
        )

        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.failures), 1)
        message = result.failures[0][1]
        for expected in (
            f"{CLOSED.path}:{CLOSED.line}: {CLOSED_URL} is merged on {DATE}",
            suite.REMOVAL,
            f"{LIMITED.path}:{LIMITED.line}: {LIMITED_URL} is rate limited",
        ):
            self.assertIn(expected, message)

    def test_a_network_error_still_fails(self) -> None:
        result = self._run([LIMITED], requests.ConnectionError("no route"))

        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.failures), 1)
        self.assertIn(f"{LIMITED.path}:{LIMITED.line}", result.failures[0][1])


if __name__ == "__main__":
    unittest.main()
