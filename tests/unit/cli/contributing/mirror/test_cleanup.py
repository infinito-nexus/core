from __future__ import annotations

import json
import os
import unittest
import urllib.error
from typing import Self
from unittest.mock import patch

import cli.contributing.mirror.cleanup.__main__ as cleanup_main


class _FakeResponse:
    def __init__(self, payload: bytes = b"[]"):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _org_probe_ok() -> _FakeResponse:
    return _FakeResponse(b"[]")


def _org_probe_404() -> _FakeResponse:
    raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)


class TestCleanupMain(unittest.TestCase):
    def _pkg(self, name: str, visibility: str = "private") -> dict:
        return {"name": name, "visibility": visibility}

    @patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}, clear=False)
    def test_dry_run_does_not_delete(self) -> None:
        packages = [self._pkg("mirror/foo")]
        responses = [
            _org_probe_ok(),
            _FakeResponse(json.dumps(packages).encode()),
            _FakeResponse(b"[]"),
        ]
        with (
            patch(
                "cli.contributing.mirror.cleanup.__main__.urllib.request.urlopen",
                side_effect=responses,
            ) as mock_open,
            patch("sys.argv", ["cleanup", "--ghcr-namespace", "acme", "--dry-run"]),
        ):
            result = cleanup_main.main()

        self.assertEqual(result, 0)
        delete_calls = [
            c for c in mock_open.call_args_list if c[0][0].get_method() == "DELETE"
        ]
        self.assertEqual(delete_calls, [])

    @patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}, clear=False)
    def test_matching_private_package_is_deleted(self) -> None:
        packages = [self._pkg("mirror/bar", "private")]
        call_count = 0

        def fake_urlopen(req):
            nonlocal call_count
            call_count += 1
            if req.get_method() == "DELETE":
                return _FakeResponse(b"")
            if call_count == 1:
                return _org_probe_ok()
            return _FakeResponse(
                json.dumps(packages if call_count == 2 else []).encode()
            )

        with (
            patch(
                "cli.contributing.mirror.cleanup.__main__.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("sys.argv", ["cleanup", "--ghcr-namespace", "acme"]),
        ):
            result = cleanup_main.main()

        self.assertEqual(result, 0)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}, clear=False)
    def test_package_outside_prefix_is_ignored(self) -> None:
        packages = [self._pkg("other/foo", "private")]
        responses = [
            _org_probe_ok(),
            _FakeResponse(json.dumps(packages).encode()),
            _FakeResponse(b"[]"),
        ]
        with (
            patch(
                "cli.contributing.mirror.cleanup.__main__.urllib.request.urlopen",
                side_effect=responses,
            ) as mock_open,
            patch("sys.argv", ["cleanup", "--ghcr-namespace", "acme"]),
        ):
            result = cleanup_main.main()

        self.assertEqual(result, 0)
        delete_calls = [
            c for c in mock_open.call_args_list if c[0][0].get_method() == "DELETE"
        ]
        self.assertEqual(delete_calls, [])

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_token_returns_error(self) -> None:
        with patch("sys.argv", ["cleanup", "--ghcr-namespace", "acme"]):
            result = cleanup_main.main()
        self.assertEqual(result, 1)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}, clear=False)
    def test_delete_failure_reports_and_exits_nonzero(self) -> None:
        packages = [self._pkg("mirror/bad", "private")]
        call_count = 0

        def fake_urlopen(req):
            nonlocal call_count
            call_count += 1
            if req.get_method() == "DELETE":
                raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
            if call_count == 1:
                return _org_probe_ok()
            return _FakeResponse(
                json.dumps(packages if call_count == 2 else []).encode()
            )

        with (
            patch(
                "cli.contributing.mirror.cleanup.__main__.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("sys.argv", ["cleanup", "--ghcr-namespace", "acme"]),
        ):
            result = cleanup_main.main()

        self.assertEqual(result, 1)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}, clear=False)
    def test_user_account_uses_user_endpoint(self) -> None:
        packages = [self._pkg("mirror/foo", "private")]
        call_count = 0

        def fake_urlopen(req):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
            if req.get_method() == "DELETE":
                self.assertIn("/user/packages/", req.full_url)
                return _FakeResponse(b"")
            return _FakeResponse(
                json.dumps(packages if call_count == 2 else []).encode()
            )

        with (
            patch(
                "cli.contributing.mirror.cleanup.__main__.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ),
            patch("sys.argv", ["cleanup", "--ghcr-namespace", "bob"]),
        ):
            result = cleanup_main.main()

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
