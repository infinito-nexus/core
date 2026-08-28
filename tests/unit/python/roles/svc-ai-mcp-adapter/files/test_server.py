"""Unit tests for the adapter's JSON-RPC request handling."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

FILES_DIR = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python"
MODULE_PATH = FILES_DIR / "server.py"

TOOLS = {"example_list": {"method": "GET", "path": "/api/things"}}

LIMITS = {
    "request_bytes": 64,
    "response_bytes": 1048576,
    "timeout_seconds": 15,
    "concurrent_requests": 4,
    "page_size": 100,
    "result_items": 5,
    "stream_seconds": 300,
}


def load():
    """Import the adapter server the way the image lays it out.

    ``server.py`` imports ``policy`` as a sibling, so its own directory has to
    be importable before the module body runs.
    """
    spec = importlib.util.spec_from_file_location("adapter_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(FILES_DIR))
    try:
        import policy

        contract = {
            "provider": "web-app-example",
            "upstream_url": "http://example:80",
            "auth_subject": "service_account",
            "tools": TOOLS,
            "limits": LIMITS,
            "schema_sha256": policy.schema_digest(TOOLS),
        }
        env = {"ADAPTER_CONTRACT": json.dumps(contract), "ADAPTER_BEARER": "real"}
        with patch.dict("os.environ", env, clear=False):
            spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(FILES_DIR))
    return module


class Recorder:
    """Capture what the handler wrote, without opening a socket."""

    def __init__(self):
        self.status = None
        self.headers = {}
        self.body = b""

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        return None


class TestNotificationHandling(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def _handle(self, request):
        handler = self.module.Handler.__new__(self.module.Handler)
        recorder = Recorder()
        handler.send_response = recorder.send_response
        handler.send_header = recorder.send_header
        handler.end_headers = recorder.end_headers
        handler.wfile = type("W", (), {"write": lambda _self, data: None})()
        handler.headers = {}
        handler.path = self.module.ENDPOINT
        payload = json.dumps(request).encode()
        handler.rfile = type("R", (), {"read": lambda _self, _n: payload})()
        handler.headers = {
            "Content-Length": str(len(payload)),
            "Authorization": "Bearer real",
        }
        handler.do_POST()
        return recorder

    def test_a_notification_is_accepted_without_a_body(self):
        recorder = self._handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self.assertEqual(recorder.status, 202)
        self.assertEqual(recorder.headers.get("Content-Length"), "0")

    def test_an_unknown_method_with_an_id_still_errors(self):
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "nope"})
        self.assertEqual(recorder.status, 400)


if __name__ == "__main__":
    unittest.main()
