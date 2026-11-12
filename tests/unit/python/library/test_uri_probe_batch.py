from __future__ import annotations

import importlib.util
import ssl
import sys
import time
import unittest
import unittest.mock as mock
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "uri_probe_batch.py"

PARAMS = {
    "method": "HEAD",
    "status_codes": [200, 404],
    "attempts": 3,
    "delay": 0,
    "timeout": 1,
    "validate_certs": False,
    "follow_redirects": "none",
    "workers": 4,
}


def _load_uri_probe_batch() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_uri_probe_batch", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_uri_probe_batch()


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _replies(*outcomes):
    queue = list(outcomes)

    def open_url(url, **kwargs):
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)

    return open_url


class ProbeTests(unittest.TestCase):
    def test_ok_answer_is_returned_without_retry(self):
        opener = mock.Mock(side_effect=_replies(200))
        with mock.patch.object(_MOD, "open_url", opener):
            self.assertEqual(_MOD.probe("http://x/a.svg", PARAMS), (200, None))
        self.assertEqual(opener.call_count, 1)

    def test_not_found_counts_as_an_answer(self):
        not_found = HTTPError("http://x/a.svg", 404, "Not Found", {}, None)
        with mock.patch.object(_MOD, "open_url", _replies(not_found)):
            self.assertEqual(_MOD.probe("http://x/a.svg", PARAMS), (404, None))

    def test_unreachable_url_is_retried_until_it_answers(self):
        opener = mock.Mock(side_effect=_replies(URLError("refused"), 200))
        with mock.patch.object(_MOD, "open_url", opener):
            self.assertEqual(_MOD.probe("http://x/a.svg", PARAMS), (200, None))
        self.assertEqual(opener.call_count, 2)

    def test_unexpected_status_stays_after_the_last_attempt(self):
        unavailable = HTTPError("http://x/a.svg", 503, "Unavailable", {}, None)
        opener = mock.Mock(side_effect=_replies(unavailable, unavailable, unavailable))
        with mock.patch.object(_MOD, "open_url", opener):
            self.assertEqual(_MOD.probe("http://x/a.svg", PARAMS), (503, None))
        self.assertEqual(opener.call_count, 3)

    def test_no_response_reports_minus_one(self):
        with mock.patch.object(_MOD, "open_url", _replies(*[OSError()] * 3)):
            status, _ = _MOD.probe("http://x/a.svg", PARAMS)
        self.assertEqual(status, -1)

    def test_no_response_names_the_error_of_the_last_attempt(self):
        refused = URLError(ConnectionRefusedError(111, "Connection refused"))
        untrusted = URLError(
            ssl.SSLCertVerificationError(
                1,
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "Missing Authority Key Identifier (_ssl.c:1085)",
            )
        )
        with mock.patch.object(_MOD, "open_url", _replies(refused, refused, untrusted)):
            status, error = _MOD.probe("https://x/", PARAMS)
        self.assertEqual(status, -1)
        self.assertIn("URLError", error)
        self.assertIn("Missing Authority Key Identifier", error)
        self.assertNotIn("Connection refused", error)

    def test_answer_after_a_failure_drops_the_error(self):
        unavailable = HTTPError("http://x/a.svg", 503, "Unavailable", {}, None)
        replies = _replies(URLError("refused"), unavailable, unavailable)
        with mock.patch.object(_MOD, "open_url", replies):
            self.assertEqual(_MOD.probe("http://x/a.svg", PARAMS), (503, None))

    def test_redirect_handling_reaches_open_url(self):
        opener = mock.Mock(side_effect=_replies(200))
        with mock.patch.object(_MOD, "open_url", opener):
            _MOD.probe("http://x/", PARAMS)
        self.assertEqual(opener.call_args.kwargs["follow_redirects"], "none")

    def test_unfollowed_redirect_is_its_own_answer(self):
        found = HTTPError("http://elsewhere/", 302, "Found", {}, None)
        params = {**PARAMS, "status_codes": [200, 302]}
        opener = mock.Mock(side_effect=_replies(found))
        with mock.patch.object(_MOD, "open_url", opener):
            self.assertEqual(_MOD.probe("http://x/", params), 302)
        self.assertEqual(opener.call_count, 1)


class ProbeAllTests(unittest.TestCase):
    def test_maps_every_name_to_its_own_result(self):
        def fake_probe(url, params):
            return (200, None) if url.endswith("ok.svg") else (404, None)

        urls = {f"slug{i}": f"http://x/{'ok' if i % 2 else 'no'}.svg" for i in range(9)}
        with mock.patch.object(_MOD, "probe", fake_probe):
            results = _MOD.probe_all(urls, PARAMS)
        self.assertEqual(list(results), list(urls))
        self.assertEqual(
            results,
            {name: (200 if i % 2 else 404, None) for i, name in enumerate(urls)},
        )

    def test_requests_run_concurrently(self):
        def slow_probe(url, params):
            time.sleep(0.2)
            return 200, None

        urls = {f"slug{i}": f"http://x/{i}.svg" for i in range(4)}
        with mock.patch.object(_MOD, "probe", slow_probe):
            start = time.monotonic()
            _MOD.probe_all(urls, PARAMS)
        self.assertLess(time.monotonic() - start, 0.6)


class MainTests(unittest.TestCase):
    def _run_main(self, results):
        module = mock.Mock()
        module.params = {**PARAMS, "urls": {url: url for url in results}}
        module.fail_json.side_effect = SystemExit(1)
        module.exit_json.side_effect = SystemExit(0)
        with (
            mock.patch.object(_MOD, "AnsibleModule", return_value=module),
            mock.patch.object(_MOD, "probe", lambda url, params: results[url]),
            self.assertRaises(SystemExit),
        ):
            _MOD.main()
        return module

    def test_failure_reports_why_each_url_got_no_answer(self):
        reason = "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>"
        module = self._run_main(
            {"https://vhost/": (-1, reason), "https://ok/": (200, None)}
        )
        kwargs = module.fail_json.call_args.kwargs
        self.assertEqual(kwargs["unanswered"], ["https://vhost/"])
        self.assertEqual(kwargs["status"], {"https://vhost/": -1, "https://ok/": 200})
        self.assertEqual(kwargs["errors"], {"https://vhost/": reason})

    def test_success_reports_an_empty_error_map(self):
        module = self._run_main({"https://ok/": (200, None)})
        module.fail_json.assert_not_called()
        self.assertEqual(module.exit_json.call_args.kwargs["errors"], {})


if __name__ == "__main__":
    unittest.main()
