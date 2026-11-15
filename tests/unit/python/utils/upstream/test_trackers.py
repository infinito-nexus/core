"""Unit tests for the tracker adapters, with every HTTP request mocked."""

from __future__ import annotations

import os
import unittest
import unittest.mock as mock

import requests

from utils.upstream import trackers
from utils.upstream.directive import GITEA, GITHUB, GITLAB, ISSUE, PULL, Reference
from utils.upstream.trackers import (
    CLOSED,
    MISSING,
    OPEN,
    RATE_LIMITED,
    UNVERIFIED,
    Status,
    api_url,
    gitea_status,
    github_status,
    gitlab_status,
    status_of,
)

GITHUB_API = "api.github.com"
DATE = "2026-10-20T10:00:00Z"
RESET_EPOCH = "1800000000"
RESET_WORDS = "at 2027-01-15T08:00:00+00:00"
GITHUB_ISSUE = Reference(GITHUB, "github.com", "owner/repo", ISSUE, 7)
GITHUB_PULL = Reference(GITHUB, "github.com", "owner/repo", PULL, 8)
GITLAB_MERGE = Reference(GITLAB, "gitlab.com", "group/sub/project", PULL, 9)
GITLAB_SELF = Reference(GITLAB, "gitlab.example", "team/app", ISSUE, 10)
GITEA_PULL = Reference(GITEA, "codeberg.org", "owner/repo", PULL, 11)
GITEA_ISSUE = Reference(GITEA, "git.example", "owner/repo", ISSUE, 12)
TOKENS = {
    "GITHUB_TOKEN": "github-token",
    "GH_TOKEN": "gh-token",
    "GITLAB_TOKEN": "gitlab-token",
}


class _Response:
    """Stand-in for the ``requests.Response`` the adapters read."""

    def __init__(self, status_code: int, body: object, headers: dict[str, str]):
        self.status_code = status_code
        self.headers = headers
        self._body = body

    def json(self) -> object:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _answer(body: object) -> _Response:
    """A 200 answer carrying *body*.

    Args:
        body: the decoded JSON, or an exception ``json()`` raises.
    """
    return _Response(200, body, {})


def _refused(code: int) -> _Response:
    """An answer with *code* and no body.

    Args:
        code: the HTTP status.
    """
    return _Response(code, None, {})


class TestGithubStatus(unittest.TestCase):
    def test_state_mapping(self) -> None:
        cases = (
            ({"state": "open"}, Status(OPEN, "open", "")),
            (
                {"state": "closed", "state_reason": "completed", "closed_at": DATE},
                Status(CLOSED, "closed (completed)", DATE),
            ),
            (
                {"state": "closed", "state_reason": "not_planned", "closed_at": DATE},
                Status(CLOSED, "closed (not planned)", DATE),
            ),
            (
                {"state": "closed", "state_reason": None, "closed_at": DATE},
                Status(CLOSED, "closed", DATE),
            ),
            (
                {
                    "state": "closed",
                    "closed_at": DATE,
                    "pull_request": {"merged_at": DATE},
                },
                Status(CLOSED, "merged", DATE),
            ),
            (
                {
                    "state": "closed",
                    "closed_at": DATE,
                    "pull_request": {"merged_at": None},
                },
                Status(CLOSED, "closed unmerged", DATE),
            ),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(github_status(body), expected)

    def test_an_unknown_state_is_unverified(self) -> None:
        self.assertEqual(github_status({"state": "draft"}).verdict, UNVERIFIED)
        self.assertEqual(github_status({}).verdict, UNVERIFIED)


class TestGitlabStatus(unittest.TestCase):
    def test_state_mapping(self) -> None:
        cases = (
            ({"state": "opened"}, Status(OPEN, "opened", "")),
            ({"state": "locked"}, Status(OPEN, "locked", "")),
            (
                {"state": "merged", "merged_at": DATE, "closed_at": None},
                Status(CLOSED, "merged", DATE),
            ),
            ({"state": "closed", "closed_at": DATE}, Status(CLOSED, "closed", DATE)),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(gitlab_status(body), expected)

    def test_an_unknown_state_is_unverified(self) -> None:
        self.assertEqual(gitlab_status({"state": "open"}).verdict, UNVERIFIED)


class TestGiteaStatus(unittest.TestCase):
    def test_state_mapping(self) -> None:
        cases = (
            ({"state": "open"}, Status(OPEN, "open", "")),
            ({"state": "closed", "closed_at": DATE}, Status(CLOSED, "closed", DATE)),
            (
                {
                    "state": "closed",
                    "merged": True,
                    "merged_at": DATE,
                    "closed_at": DATE,
                },
                Status(CLOSED, "merged", DATE),
            ),
            (
                {"state": "closed", "merged": False, "closed_at": DATE},
                Status(CLOSED, "closed", DATE),
            ),
            (
                {
                    "state": "closed",
                    "closed_at": DATE,
                    "pull_request": {"merged": True, "merged_at": DATE},
                },
                Status(CLOSED, "merged", DATE),
            ),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(gitea_status(body), expected)

    def test_an_unknown_state_is_unverified(self) -> None:
        self.assertEqual(gitea_status({"state": "opened"}).verdict, UNVERIFIED)


class TestApiUrl(unittest.TestCase):
    def test_each_forge_names_its_own_endpoint(self) -> None:
        cases = (
            (GITHUB_ISSUE, f"https://{GITHUB_API}/repos/owner/repo/issues/7"),
            (GITHUB_PULL, f"https://{GITHUB_API}/repos/owner/repo/issues/8"),
            (
                GITLAB_MERGE,
                (
                    f"https://{GITLAB_MERGE.host}/api/v4/projects/"
                    "group%2Fsub%2Fproject/merge_requests/9"
                ),
            ),
            (
                GITLAB_SELF,
                f"https://{GITLAB_SELF.host}/api/v4/projects/team%2Fapp/issues/10",
            ),
            (
                GITEA_PULL,
                f"https://{GITEA_PULL.host}/api/v1/repos/owner/repo/pulls/11",
            ),
            (
                GITEA_ISSUE,
                f"https://{GITEA_ISSUE.host}/api/v1/repos/owner/repo/issues/12",
            ),
        )
        for reference, expected in cases:
            with self.subTest(reference=reference):
                self.assertEqual(api_url(reference), expected)


class TestTokens(unittest.TestCase):
    def _headers(self, reference: Reference, environ: dict[str, str]) -> dict:
        with mock.patch.dict(os.environ, environ, clear=True):
            return trackers._headers(reference)

    def test_github_prefers_github_token_and_falls_back_to_gh_token(self) -> None:
        self.assertEqual(
            self._headers(GITHUB_ISSUE, TOKENS)["Authorization"], "Bearer github-token"
        )
        self.assertEqual(
            self._headers(GITHUB_ISSUE, {"GH_TOKEN": "gh-token"})["Authorization"],
            "Bearer gh-token",
        )
        self.assertNotIn("Authorization", self._headers(GITHUB_ISSUE, {}))

    def test_the_gitlab_token_goes_to_gitlab_com_only(self) -> None:
        self.assertEqual(
            self._headers(GITLAB_MERGE, TOKENS)["PRIVATE-TOKEN"], "gitlab-token"
        )
        self.assertNotIn("PRIVATE-TOKEN", self._headers(GITLAB_SELF, TOKENS))

    def test_gitea_never_carries_a_token(self) -> None:
        headers = self._headers(GITEA_ISSUE, TOKENS)
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("PRIVATE-TOKEN", headers)


class TestStatusOf(unittest.TestCase):
    def setUp(self) -> None:
        self.sleep = mock.Mock()
        for patcher in (
            mock.patch.object(trackers.time, "sleep", self.sleep),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ask(self, reference: Reference, *answers: object) -> tuple[Status, mock.Mock]:
        with mock.patch.object(
            trackers.requests, "get", side_effect=list(answers)
        ) as get:
            return status_of(reference), get

    def test_an_open_answer_comes_from_the_items_api_url(self) -> None:
        status, get = self._ask(GITHUB_PULL, _answer({"state": "open"}))
        self.assertEqual(status, Status(OPEN, "open", ""))
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], api_url(GITHUB_PULL))
        self.assertEqual(get.call_args.kwargs["timeout"], trackers.TIMEOUT_SECONDS)

    def test_a_merged_pull_request_is_closed(self) -> None:
        status, _get = self._ask(
            GITEA_PULL,
            _answer({"state": "closed", "merged": True, "merged_at": DATE}),
        )
        self.assertEqual(status, Status(CLOSED, "merged", DATE))

    def test_gone_items_are_missing(self) -> None:
        for code in (404, 410):
            with self.subTest(code=code):
                status, _get = self._ask(GITHUB_ISSUE, _refused(code))
                self.assertEqual(status, Status(MISSING, f"HTTP {code}", ""))

    def test_an_exhausted_rate_limit_is_rate_limited_without_a_retry(self) -> None:
        status, get = self._ask(
            GITHUB_ISSUE,
            _Response(
                403,
                None,
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": RESET_EPOCH},
            ),
        )
        self.assertEqual(
            status, Status(RATE_LIMITED, "rate limited (HTTP 403)", RESET_WORDS)
        )
        get.assert_called_once()
        self.sleep.assert_not_called()

    def test_a_secondary_rate_limit_names_its_delay(self) -> None:
        status, _get = self._ask(
            GITHUB_ISSUE, _Response(403, None, {"Retry-After": "60"})
        )
        self.assertEqual(
            status, Status(RATE_LIMITED, "rate limited (HTTP 403)", "in 60 s")
        )

    def test_a_429_that_survives_the_retries_is_rate_limited(self) -> None:
        answer = _Response(429, None, {"RateLimit-Reset": RESET_EPOCH})
        status, get = self._ask(GITLAB_MERGE, answer, answer, answer)
        self.assertEqual(
            status, Status(RATE_LIMITED, "rate limited (HTTP 429)", RESET_WORDS)
        )
        self.assertEqual(get.call_count, 3)

    def test_a_rate_limit_without_a_reset_header_says_so(self) -> None:
        status, _get = self._ask(GITEA_ISSUE, *[_refused(429)] * 3)
        self.assertEqual(
            status,
            Status(RATE_LIMITED, "rate limited (HTTP 429)", "at an unknown time"),
        )

    def test_refusals_are_unverified(self) -> None:
        for code, state in (
            (401, "auth wall (HTTP 401)"),
            (403, "auth wall (HTTP 403)"),
            (400, "unexpected answer (HTTP 400)"),
        ):
            with self.subTest(code=code):
                status, _get = self._ask(GITLAB_MERGE, _refused(code))
                self.assertEqual(status, Status(UNVERIFIED, state, ""))

    def test_a_transient_failure_is_retried(self) -> None:
        for transient in (_refused(429), _refused(502), requests.ConnectionError("x")):
            with self.subTest(transient=transient):
                status, get = self._ask(
                    GITHUB_ISSUE, transient, _answer({"state": "open"})
                )
                self.assertEqual(status.verdict, OPEN)
                self.assertEqual(get.call_count, 2)

    def test_a_failure_that_persists_is_unverified(self) -> None:
        status, get = self._ask(GITEA_ISSUE, *[_refused(503)] * 3)
        self.assertEqual(status, Status(UNVERIFIED, "server error (HTTP 503)", ""))
        self.assertEqual(get.call_count, 3)

        status, get = self._ask(GITEA_ISSUE, *[requests.Timeout("slow")] * 3)
        self.assertEqual(status.verdict, UNVERIFIED)
        self.assertTrue(status.state.startswith("Timeout"), status.state)
        self.assertEqual(get.call_count, 3)

    def test_an_answer_that_is_no_json_object_is_unverified(self) -> None:
        for body, state in (
            (ValueError("not json"), "the answer is not JSON"),
            ([{"state": "open"}], "the answer is not a JSON object"),
        ):
            with self.subTest(state=state):
                status, _get = self._ask(GITLAB_SELF, _answer(body))
                self.assertEqual(status, Status(UNVERIFIED, state, ""))


if __name__ == "__main__":
    unittest.main()
