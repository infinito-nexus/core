"""Unit tests for ``roles/sys-svc-compose/files/python/http_request.py``."""

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

SCRIPT_PATH = PROJECT_ROOT / "roles/sys-svc-compose/files/python/http_request.py"
URL = "http://127.0.0.1:5678/rest/login"
BODY = json.dumps({"emailOrLdapLoginId": "a@example.org"})


def _headers(content_type: str) -> Message:
    headers = Message()
    headers["Content-Type"] = content_type
    return headers


def _run(
    urlopen: MagicMock,
    *,
    method: str,
    body: str,
    headers: dict[str, str] | None = None,
    build_opener: MagicMock | None = None,
) -> dict:
    stdout = io.StringIO()
    env = {
        "HTTP_METHOD": method,
        "HTTP_URL": URL,
        "HTTP_PROXY": "http://proxy.invalid:3128",
    }
    body_b64 = base64.b64encode(body.encode()).decode()
    headers_b64 = base64.b64encode(json.dumps(headers or {}).encode()).decode()
    program = (
        f"BODY_B64 = {json.dumps(body_b64)}\n"
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
    return json.loads(stdout.getvalue())


def _ok(content: bytes) -> MagicMock:
    response = MagicMock(status=200, headers=_headers("application/json"))
    response.read.return_value = content
    urlopen = MagicMock()
    urlopen.return_value.__enter__.return_value = response
    return urlopen


class TestHttpRequest(unittest.TestCase):
    def test_environment_proxies_are_ignored(self):
        build_opener = MagicMock()

        _run(_ok(b"ok"), method="GET", body="", build_opener=build_opener)

        (handler,) = build_opener.call_args.args
        self.assertIsInstance(handler, urllib.request.ProxyHandler)
        self.assertEqual(handler.proxies, {})

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
            {
                "status": 200,
                "content_type": "application/json",
                "content": '{"data": {}}',
            },
        )

    def test_extra_headers_are_sent(self):
        urlopen = _ok(b"ok")

        _run(urlopen, method="POST", body=BODY, headers={"Authorization": "Basic YTpi"})

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Basic YTpi")
        self.assertEqual(request.get_header("Content-type"), "application/json")

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
