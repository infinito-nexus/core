import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/sys-ctl-hlth-git-settings/files/python"))
from git import core as git_core
from git import gitea as git_gitea
from git import github as git_github
from git import gitlab as git_gitlab


class TestFailureReason(unittest.TestCase):
    def test_rate_limit(self):
        reason = git_core.failure_reason(
            403,
            json.dumps({"message": "API rate limit exceeded"}).encode(),
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "42"},
        )
        self.assertEqual(reason, "HTTP 403: rate limit exceeded, resets at epoch 42")

    def test_gitlab_rate_limit_headers(self):
        reason = git_core.failure_reason(
            403, b"{}", {"RateLimit-Remaining": "0", "RateLimit-Reset": "7"}
        )
        self.assertEqual(reason, "HTTP 403: rate limit exceeded, resets at epoch 7")

    def test_secondary_rate_limit(self):
        self.assertIn("rate limit", git_core.failure_reason(429, b"", {}))

    def test_permission(self):
        reason = git_core.failure_reason(
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
            self.assertTrue(git_core.allowed_url(url), url)

    def test_other_schemes_and_public_http_are_refused(self):
        for url in (
            "http://api.github.example/repos/o/r",
            "http://10.0.0.1/",
            "file:///etc/passwd",
            "ftp://api.github.example/",
            "http:///nohost",
        ):
            self.assertFalse(git_core.allowed_url(url), url)

    def test_api_refuses_a_public_http_base_url(self):
        with self.assertRaises(ValueError):
            git_core.Api("http://api.github.example", "t", 5, {})

    def test_a_non_https_next_link_is_a_failed_check(self):
        api = git_core.Api("https://api.github.example", "t", 5, {})
        with self.assertRaises(git_core.CheckError):
            api._open("http://evil.example/next")


class TestHelpers(unittest.TestCase):
    def test_read_token_strips_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            path.write_text("  secret-token\n", encoding="utf-8")
            self.assertEqual(git_core.read_token(str(path)), "secret-token")

    def test_emit_logs_the_summary_as_info_and_findings_as_warnings(self):
        events = [{"x_kind": "drift", "x_a": "1"}, {"x_kind": "run", "x_n": "1"}]
        with (
            mock.patch.object(git_core.syslog, "openlog") as openlog,
            mock.patch.object(git_core.syslog, "syslog") as log,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            git_core.emit("tag-x", events, "x_kind")
        openlog.assert_called_once_with(
            ident="tag-x", facility=git_core.syslog.LOG_DAEMON
        )
        self.assertEqual(
            [call.args for call in log.call_args_list],
            [
                (git_core.syslog.LOG_WARNING, json.dumps(events[0])),
                (git_core.syslog.LOG_INFO, json.dumps(events[1])),
            ],
        )
        self.assertEqual(out.getvalue().splitlines(), [json.dumps(e) for e in events])


class TestProviders(unittest.TestCase):
    def sent_headers(self, adapter):
        api = adapter.client("https://api.forge.example", "tok", 5, "agent-x")
        with mock.patch.object(git_core.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            api.get("/x")
        return dict(urlopen.call_args.args[0].header_items())

    def test_each_provider_authenticates_its_own_way(self):
        self.assertEqual(self.sent_headers(git_github)["Authorization"], "Bearer tok")
        self.assertEqual(self.sent_headers(git_gitea)["Authorization"], "token tok")
        self.assertEqual(self.sent_headers(git_gitlab)["Private-token"], "tok")
        for adapter in (git_github, git_gitea, git_gitlab):
            self.assertEqual(self.sent_headers(adapter)["User-agent"], "agent-x")

    def test_registry_knows_exactly_the_three_providers(self):
        self.assertEqual(git_core.PROVIDERS, ("github", "gitea", "gitlab"))
        for name in git_core.PROVIDERS:
            self.assertEqual(git_core.provider(name).NAME, name)


if __name__ == "__main__":
    unittest.main()
