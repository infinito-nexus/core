from __future__ import annotations

import base64
import contextlib
import io
import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-xwiki/files/python/http_call.py"
AUTH = {"Authorization": "Basic c3VwZXJhZG1pbjpzZWNyZXQ="}
ROUTES = {
    ("GET", "/rest/spaces"): (
        200,
        [
            ("Content-Type", "application/xml"),
            ("XWiki-Form-Token", "tok"),
            ("Set-Cookie", "JSESSIONID=abc; Path=/"),
            ("Set-Cookie", "xwiki=1; Path=/"),
        ],
        b"<spaces/>",
    ),
    ("GET", "/moved"): (302, [("Location", "/rest/spaces")], b""),
    ("DELETE", "/moved"): (302, [("Location", "/rest/spaces")], b""),
    ("PUT", "/pages/X"): (201, [], b"created"),
    ("GET", "/missing"): (404, [], b"gone"),
}


class _XWiki(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self._serve()

    def do_PUT(self):
        self._serve()

    def do_DELETE(self):
        self._serve()

    def _serve(self):
        length = self.headers["Content-Length"]
        body = self.rfile.read(int(length)) if length else b""
        self.server.received.append((self.command, self.path, self.headers, body))
        status, headers, content = ROUTES[(self.command, self.path)]
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _program(headers: dict, body: str) -> str:
    """Returns the stdin program tasks/utils/http.yml builds for ``headers`` and ``body``."""
    headers_b64 = base64.b64encode(json.dumps(headers).encode()).decode()
    body_b64 = base64.b64encode(body.encode()).decode()
    return (
        f"HEADERS_B64 = {json.dumps(headers_b64)}\n"
        f"BODY_B64 = {json.dumps(body_b64)}\n" + read_text(str(SCRIPT_PATH))
    )


def _call(url: str, method: str, follow: str, headers: dict, body: str) -> dict:
    stdout = io.StringIO()
    env = {
        "HTTP_METHOD": method,
        "HTTP_URL": url,
        "HTTP_FOLLOW_REDIRECTS": follow,
        "HTTP_TIMEOUT": "5",
    }
    with patch.dict("os.environ", env, clear=True), contextlib.redirect_stdout(stdout):
        exec(
            compile(_program(headers, body), "<stdin>", "exec"),
            {"__name__": "__main__"},
        )
    return json.loads(stdout.getvalue())


class TestHttpCall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _XWiki)
        cls.server.received = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.received.clear()

    def test_get_reports_status_headers_cookies_and_content(self):
        answer = _call(f"{self.base}/rest/spaces", "GET", "safe", AUTH, "")

        self.assertEqual(answer["status"], 200)
        self.assertFalse(answer["redirected"])
        self.assertEqual(answer["url"], f"{self.base}/rest/spaces")
        self.assertEqual(answer["headers"]["xwiki-form-token"], "tok")
        self.assertEqual(
            answer["headers"]["set-cookie"], "JSESSIONID=abc; Path=/, xwiki=1; Path=/"
        )
        self.assertEqual(answer["cookies_string"], "JSESSIONID=abc; xwiki=1")
        self.assertEqual(answer["content"], "<spaces/>")
        _method, _path, headers, body = self.server.received[0]
        self.assertEqual(headers["Authorization"], AUTH["Authorization"])
        self.assertEqual(body, b"")

    def test_safe_follows_a_get_redirect_with_its_headers(self):
        answer = _call(f"{self.base}/moved", "GET", "safe", AUTH, "")

        self.assertEqual(answer["status"], 200)
        self.assertTrue(answer["redirected"])
        self.assertEqual(answer["url"], f"{self.base}/rest/spaces")
        self.assertEqual(
            [headers["Authorization"] for _m, _p, headers, _b in self.server.received],
            [AUTH["Authorization"], AUTH["Authorization"]],
        )

    def test_none_answers_with_the_redirect_itself(self):
        answer = _call(f"{self.base}/moved", "GET", "none", AUTH, "")

        self.assertEqual(answer["status"], 302)
        self.assertFalse(answer["redirected"])
        self.assertEqual(answer["headers"]["location"], "/rest/spaces")
        self.assertEqual(len(self.server.received), 1)

    def test_safe_never_follows_the_redirect_of_a_write(self):
        answer = _call(f"{self.base}/moved", "DELETE", "safe", AUTH, "")

        self.assertEqual(answer["status"], 302)
        self.assertEqual(len(self.server.received), 1)

    def test_put_sends_the_body_verbatim_with_the_given_headers(self):
        headers = {
            **AUTH,
            "Content-Type": "application/xml",
            "Cookie": "JSESSIONID=abc",
        }

        answer = _call(f"{self.base}/pages/X", "PUT", "safe", headers, "<page/>\n")

        self.assertEqual(answer["status"], 201)
        method, _path, received, body = self.server.received[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(body, b"<page/>\n")
        self.assertEqual(received["Content-Type"], "application/xml")
        self.assertEqual(received["Cookie"], "JSESSIONID=abc")

    def test_an_http_error_status_is_an_answer(self):
        answer = _call(f"{self.base}/missing", "GET", "safe", AUTH, "")

        self.assertEqual(answer["status"], 404)
        self.assertEqual(answer["content"], "gone")

    def test_a_connection_failure_raises(self):
        with self.assertRaises(urllib.error.URLError):
            _call("http://127.0.0.1:1/", "GET", "safe", AUTH, "")

    def test_an_unknown_redirect_mode_is_rejected(self):
        with self.assertRaises(KeyError):
            _call(f"{self.base}/rest/spaces", "GET", "all", AUTH, "")


if __name__ == "__main__":
    unittest.main()
