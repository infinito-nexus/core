from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from crossposter import web

RECEIVED: dict[str, bytes] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return None

    def _answer(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/json":
            self._answer(200, b'{"ok": true}', {"Content-Type": "application/json"})
        elif self.path == "/busy":
            self._answer(503, b"busy", {"Retry-After": "30"})
        elif self.path == "/media":
            self._answer(200, b"\xff\xd8" + b"x" * 4096, {})
        else:
            self._answer(404, b"missing", {})

    def do_PUT(self) -> None:
        RECEIVED[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
        self._answer(201, b"", {})


class ServerFixture:
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()


class TestRequest(ServerFixture, unittest.TestCase):
    def test_json_answers_are_decoded(self) -> None:
        self.assertEqual(web.get_json(self.base + "/json", {}), {"ok": True})

    def test_a_server_error_is_transient_and_keeps_its_headers(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", self.base + "/busy", {}, None, (200,))
        self.assertTrue(caught.exception.transient)
        self.assertEqual(caught.exception.headers.get("Retry-After"), "30")

    def test_a_client_error_is_permanent(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", self.base + "/gone", {}, None, (200,))
        self.assertFalse(caught.exception.transient)

    def test_an_unreachable_host_is_transient(self) -> None:
        with self.assertRaises(web.RequestError) as caught:
            web.request("GET", "http://127.0.0.1:9/", {}, None, (200,))
        self.assertTrue(caught.exception.transient)


class TestStreaming(ServerFixture, unittest.TestCase):
    def test_media_streams_to_disk_and_back(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            local = web.download(self.base + "/media", {}, Path(folder) / "media.jpg")
            self.assertEqual(local.stat().st_size, 4098)
            web.upload("PUT", self.base + "/target", {}, local, (201,))
        self.assertEqual(RECEIVED["/target"][:2], b"\xff\xd8")
        self.assertEqual(len(RECEIVED["/target"]), 4098)
