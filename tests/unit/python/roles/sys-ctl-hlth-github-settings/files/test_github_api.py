import importlib.util
import json
import unittest

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
            github_api.Api("http://api.github.example", "t", 5)

    def test_a_non_https_next_link_is_a_failed_check(self):
        api = github_api.Api("https://api.github.example", "t", 5)
        with self.assertRaises(github_api.CheckError):
            api._open("http://evil.example/next")


if __name__ == "__main__":
    unittest.main()
