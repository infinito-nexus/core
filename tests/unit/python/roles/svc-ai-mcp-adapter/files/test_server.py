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

TOOLS = {
    "example_list": {"method": "GET", "path": "/api/things"},
    "example_get": {"method": "GET", "path": "/api/things/{id}"},
}

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


class FakeResponse:
    """Stands in for what the opener returns."""

    def __init__(self, body=b"{}"):
        self._body = body

    def read(self, _limit=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TestFixedTarget(unittest.TestCase):
    """No client input may move the request off the contracted upstream."""

    def setUp(self):
        self.module = load()

    def _opened(self, tool, arguments):
        seen = {}

        def fake_open(request, timeout=None):
            seen["url"] = request.full_url
            return FakeResponse()

        spec = self.module.CONTRACT["tools"][tool]
        with patch.object(self.module.OPENER, "open", fake_open):
            self.module.call_upstream(spec["method"], spec["path"], arguments)
        return seen["url"]

    def test_the_request_stays_on_the_contracted_origin(self):
        url = self._opened("example_get", {"id": "7"})
        self.assertEqual("http://example:80/api/things/7", url)

    def test_an_argument_naming_another_host_cannot_move_the_request(self):
        url = self._opened("example_get", {"id": "http://evil.example/steal"})
        self.assertTrue(
            url.startswith("http://example:80/api/things/"),
            f"a client argument reached outside the contracted origin: {url}",
        )
        self.assertNotIn("evil.example/steal", url)

    def test_a_path_argument_cannot_escape_its_segment(self):
        url = self._opened("example_get", {"id": "../../admin"})
        self.assertEqual("http://example:80/api/things/..%2F..%2Fadmin", url)

    def test_an_uncontracted_argument_lands_in_the_query_not_the_path(self):
        url = self._opened("example_get", {"id": "7", "extra": "/etc/passwd"})
        self.assertTrue(url.startswith("http://example:80/api/things/7?"), url)
        self.assertIn("extra=%2Fetc%2Fpasswd", url)

    def test_an_upstream_redirect_is_refused_rather_than_followed(self):
        handler = self.module.NoRedirect()
        self.assertIsNone(
            handler.redirect_request(
                None, None, 302, "Found", {}, "http://evil.example/"
            ),
            "urllib copies the request headers onto the redirect target, so "
            "following one would hand the upstream credential to whoever the "
            "upstream named",
        )


class TestConcurrencyCeiling(unittest.TestCase):
    """The declared ``concurrent_requests`` is refused past, not just declared.

    ``ThreadingHTTPServer`` starts a thread per connection and consults no
    contract, so before the handler refused the surplus itself the limit was
    validated at load time and then never applied.
    """

    def setUp(self):
        self.module = load()

    def _handle(self, request, result=None, error=None):
        handler = self.module.Handler.__new__(self.module.Handler)
        recorder = Recorder()
        handler.send_response = recorder.send_response
        handler.send_header = recorder.send_header
        handler.end_headers = recorder.end_headers
        written = []
        handler.wfile = type(
            "W", (), {"write": lambda _s, data: written.append(data)}
        )()
        handler.path = self.module.ENDPOINT
        payload = json.dumps(request).encode()
        handler.rfile = type("R", (), {"read": lambda _s, _n: payload})()
        handler.headers = {
            "Content-Length": str(len(payload)),
            "Authorization": "Bearer real",
        }

        def _dispatch(*_args):
            if error is not None:
                raise error
            return result

        with patch.object(self.module, "dispatch", _dispatch):
            handler.do_POST()
        recorder.body = b"".join(written)
        return recorder

    def test_a_request_within_the_ceiling_is_served(self):
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        self.assertEqual(200, recorder.status)

    def test_the_surplus_request_is_refused_not_queued(self):
        for _ in range(LIMITS["concurrent_requests"]):
            self.module.IN_FLIGHT.acquire()
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        self.assertEqual(503, recorder.status)
        self.assertIn("too_many_concurrent_requests", recorder.body.decode())

    def test_a_served_request_gives_its_slot_back(self):
        for _ in range(LIMITS["concurrent_requests"]):
            self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        self.assertEqual(
            200,
            recorder.status,
            "a slot held past the response would let the ceiling shrink to zero "
            "over the adapter's lifetime",
        )

    def test_a_failed_request_gives_its_slot_back(self):
        for _ in range(LIMITS["concurrent_requests"]):
            self._handle(
                {"jsonrpc": "2.0", "id": 1, "method": "x"},
                error=RuntimeError("upstream down"),
            )
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        self.assertEqual(200, recorder.status)

    def test_a_notification_takes_no_slot(self):
        for _ in range(LIMITS["concurrent_requests"] * 2):
            self._handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        recorder = self._handle({"jsonrpc": "2.0", "id": 1, "method": "x"}, result={})
        self.assertEqual(200, recorder.status)


if __name__ == "__main__":
    unittest.main()
