"""Unit tests for ``roles/sys-svc-compose/files/python/http_request.py``."""

from __future__ import annotations

import contextlib
import io
import json
import runpy
import unittest
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/sys-svc-compose/files/python/http_request.py"
URL = "http://127.0.0.1:5678/rest/login"
BODY = json.dumps({"emailOrLdapLoginId": "a@example.org"})


def _headers(content_type: str) -> Message:
    headers = Message()
    headers["Content-Type"] = content_type
    return headers


def _run(urlopen: MagicMock, *, method: str, body: str) -> dict:
    stdout = io.StringIO()
    env = {"HTTP_METHOD": method, "HTTP_URL": URL, "HTTP_BODY": body}
    with (
        patch.dict("os.environ", env, clear=True),
        patch("urllib.request.urlopen", urlopen),
        contextlib.redirect_stdout(stdout),
    ):
        runpy.run_path(str(SCRIPT_PATH))
    return json.loads(stdout.getvalue())


def _ok(content: bytes) -> MagicMock:
    response = MagicMock(status=200, headers=_headers("application/json"))
    response.read.return_value = content
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = response
    return urlopen


class TestHttpRequest(unittest.TestCase):
    def test_post_sends_json_body_and_reports_answer(self):
        urlopen = _ok(b'{"data": {}}')

        answer = _run(urlopen, method="POST", body=BODY)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, BODY.encode())
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            answer,
            {"status": 200, "content_type": "application/json", "content": '{"data": {}}'},
        )

    def test_empty_body_sends_none(self):
        urlopen = _ok(b"ok")

        _run(urlopen, method="GET", body="")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header("Content-type"))

    def test_http_error_is_an_answer_not_a_failure(self):
        error = urllib.error.HTTPError(
            URL,
            401,
            "Unauthorized",
            _headers("application/json; charset=utf-8"),
            io.BytesIO(b'{"message": "Wrong username or password."}'),
        )

        answer = _run(MagicMock(side_effect=error), method="POST", body=BODY)

        self.assertEqual(answer["status"], 401)
        self.assertEqual(answer["content_type"], "application/json; charset=utf-8")
        self.assertIn("Wrong username", answer["content"])

    def test_connection_failure_raises(self):
        with self.assertRaises(urllib.error.URLError):
            _run(
                MagicMock(side_effect=urllib.error.URLError("refused")),
                method="POST",
                body=BODY,
            )


if __name__ == "__main__":
    unittest.main()
