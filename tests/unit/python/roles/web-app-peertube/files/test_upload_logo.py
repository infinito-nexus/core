"""Unit tests for ``roles/web-app-peertube/files/python/upload_logo.py``."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import unittest
import urllib.error
import urllib.request
from email.message import Message
from unittest.mock import MagicMock, patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-peertube/files/python/upload_logo.py"
URL = "http://127.0.0.1:9000/api/v1/config/instance-logo/favicon/pick"
LOGO = b"\x89PNG\r\n\x1a\n\x00\xff binary"
HEADERS = {"Host": "video.example.org", "Authorization": "Bearer t0ken"}


def _run(urlopen: MagicMock, build_opener: MagicMock | None = None) -> str:
    stdout = io.StringIO()
    env = {"HTTP_URL": URL, "HTTP_PROXY": "http://proxy.invalid:3128"}
    logo_b64 = base64.b64encode(LOGO).decode()
    headers_b64 = base64.b64encode(json.dumps(HEADERS).encode()).decode()
    program = (
        f"LOGO_B64 = {json.dumps(logo_b64)}\n"
        f"HEADERS_B64 = {json.dumps(headers_b64)}\n" + read_text(str(SCRIPT_PATH))
    )
    opener_factory = build_opener or MagicMock()
    opener_factory.return_value = MagicMock(open=urlopen)
    with (
        patch.dict("os.environ", env, clear=True),
        patch("urllib.request.build_opener", opener_factory),
        contextlib.redirect_stdout(stdout),
    ):
        exec(compile(program, "<stdin>", "exec"), {"__name__": "__main__"})
    return stdout.getvalue()


def _answer(status: int) -> MagicMock:
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = MagicMock(status=status)
    return urlopen


class TestUploadLogo(unittest.TestCase):
    def test_posts_the_png_as_logofile_form_data(self):
        urlopen = _answer(204)

        self.assertEqual(_run(urlopen), "204\n")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_method(), "POST")
        content_type = request.get_header("Content-type")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        boundary = content_type.split("boundary=", 1)[1]
        self.assertTrue(request.data.startswith(f"--{boundary}\r\n".encode()))
        self.assertIn(b'name="logofile"', request.data)
        self.assertIn(b"Content-Type: image/png\r\n\r\n" + LOGO + b"\r\n", request.data)
        self.assertTrue(request.data.endswith(f"\r\n--{boundary}--\r\n".encode()))

    def test_caller_headers_are_sent(self):
        urlopen = _answer(200)

        _run(urlopen)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer t0ken")
        self.assertEqual(request.get_header("Host"), "video.example.org")

    def test_environment_proxies_are_ignored(self):
        build_opener = MagicMock()

        _run(_answer(204), build_opener=build_opener)

        (handler,) = build_opener.call_args.args
        self.assertIsInstance(handler, urllib.request.ProxyHandler)
        self.assertEqual(handler.proxies, {})

    def test_http_error_is_an_answer_not_a_failure(self):
        error = urllib.error.HTTPError(
            URL, 401, "Unauthorized", Message(), io.BytesIO(b"")
        )

        self.assertEqual(_run(MagicMock(side_effect=error)), "401\n")

    def test_connection_failure_raises(self):
        with self.assertRaises(urllib.error.URLError):
            _run(MagicMock(side_effect=urllib.error.URLError("refused")))


if __name__ == "__main__":
    unittest.main()
