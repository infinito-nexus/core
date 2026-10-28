import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "github_api",
    PROJECT_ROOT / "roles/sys-ctl-hlth-github-settings/files/python/github_api.py",
)
github_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(github_api)


class TestFailureReason(unittest.TestCase):
    def test_rate_limit(self):
        reason = github_api.failure_reason(
            403,
            json.dumps({"message": "API rate limit exceeded"}).encode(),
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "42"},
        )
        self.assertEqual(reason, "HTTP 403: rate limit exceeded, resets at epoch 42")

    def test_secondary_rate_limit(self):
        self.assertIn("rate limit", github_api.failure_reason(429, b"", {}))

    def test_permission(self):
        reason = github_api.failure_reason(
            403,
            json.dumps(
                {"message": "Resource not accessible by personal access token"}
            ).encode(),
            {"X-RateLimit-Remaining": "4999"},
        )
        self.assertEqual(
            reason, "HTTP 403: Resource not accessible by personal access token"
        )


class TestAllowedUrl(unittest.TestCase):
    def test_https_and_local_stubs_are_allowed(self):
        for url in (
            "https://api.github.example/repos/o/r",
            "http://127.0.0.1:8080/repos/o/r",
            "http://localhost:8080/",
            "http://github-api-stub:8080/",
            "http://[::1]:8080/",
        ):
            self.assertTrue(github_api.allowed_url(url), url)

    def test_other_schemes_and_public_http_are_refused(self):
        for url in (
            "http://api.github.example/repos/o/r",
            "http://10.0.0.1/",
            "file:///etc/passwd",
            "ftp://api.github.example/",
            "http:///nohost",
        ):
            self.assertFalse(github_api.allowed_url(url), url)

    def test_api_refuses_a_public_http_base_url(self):
        with self.assertRaises(ValueError):
            github_api.Api("http://api.github.example", "t", 5, "test")

    def test_a_non_https_next_link_is_a_failed_check(self):
        api = github_api.Api("https://api.github.example", "t", 5, "test")
        with self.assertRaises(github_api.CheckError):
            api._open("http://evil.example/next")


class TestHelpers(unittest.TestCase):
    def test_read_token_strips_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            path.write_text("  secret-token\n", encoding="utf-8")
            self.assertEqual(github_api.read_token(str(path)), "secret-token")

    def test_emit_logs_the_summary_as_info_and_findings_as_warnings(self):
        events = [{"x_kind": "drift", "x_a": "1"}, {"x_kind": "run", "x_n": "1"}]
        with (
            mock.patch.object(github_api.syslog, "openlog") as openlog,
            mock.patch.object(github_api.syslog, "syslog") as log,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            github_api.emit("tag-x", events, "x_kind")
        openlog.assert_called_once_with(
            ident="tag-x", facility=github_api.syslog.LOG_DAEMON
        )
        self.assertEqual(
            [call.args for call in log.call_args_list],
            [
                (github_api.syslog.LOG_WARNING, json.dumps(events[0])),
                (github_api.syslog.LOG_INFO, json.dumps(events[1])),
            ],
        )
        self.assertEqual(out.getvalue().splitlines(), [json.dumps(e) for e in events])

    def test_user_agent_is_sent(self):
        api = github_api.Api("https://api.github.example", "t", 5, "agent-x")
        with mock.patch.object(github_api.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            api.get("/x")
        self.assertEqual(urlopen.call_args.args[0].get_header("User-agent"), "agent-x")


if __name__ == "__main__":
    unittest.main()
