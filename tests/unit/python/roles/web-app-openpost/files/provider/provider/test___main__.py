from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
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

    def test_the_http_handler_serves_the_app(self) -> None:
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), entry.handler_for(entry.application(CONFIG))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/__fake/health"
        with urllib.request.urlopen(url, timeout=5) as answer:
            self.assertEqual((answer.status, answer.read()), (200, b"ok"))

    def test_health_fails_without_a_server(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "provider.json"
            path.write_text(json.dumps({**CONFIG, "http_port": 1}))
            self.assertEqual(entry.health(entry.load(str(path))), 1)


if __name__ == "__main__":
    unittest.main()
