from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from provider import __main__ as entry

CONFIG = {
    "http_port": 0,
    "https_port": 0,
    "certificate": "/unused.crt",
    "key": "/unused.key",
    "linkedin": {
        "clients": {
            "simulator-linkedin": {
                "secret": "s",
                "name": "OpenPost",
                "redirect_uris": ["https://publish.example/cb"],
            }
        }
    },
}


class TestEntry(unittest.TestCase):
    def test_the_config_registers_its_clients(self) -> None:
        app = entry.application(CONFIG)
        client = app.clients["simulator-linkedin"]
        self.assertEqual(client.redirect_uris, ("https://publish.example/cb",))

    def _request(self, method: str, path: str) -> http.client.HTTPResponse:
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), entry.handler_for(entry.application(CONFIG))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=5
        )
        self.addCleanup(connection.close)
        connection.request(method, path)
        return connection.getresponse()

    def test_the_http_handler_serves_the_app(self) -> None:
        answer = self._request("GET", "/__fake/health")
        self.assertEqual((answer.status, answer.read()), (200, b"ok"))

    def test_head_answers_like_get_without_a_body(self) -> None:
        get = self._request("GET", "/")
        head = self._request("HEAD", "/")
        self.assertEqual(head.status, 200)
        self.assertEqual(
            head.getheader("Content-Length"), get.getheader("Content-Length")
        )
        self.assertEqual(head.read(), b"")

    def test_health_fails_without_a_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "provider.json"
            path.write_text(json.dumps({**CONFIG, "http_port": 1}))
            self.assertEqual(entry.health(entry.load(str(path))), 1)


if __name__ == "__main__":
    unittest.main()
