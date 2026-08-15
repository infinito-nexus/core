"""Unit tests for the deploy-time MCP provider contract probe."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import queue
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/probe/contract.py"

ENV = {
    "MCP_URL": "http://provider:8080/mcp",
    "MCP_TRANSPORT": "streamable_http",
    "MCP_PATH_KEY": "",
    "MCP_AUTH_HEADER": "Bearer real",
    "MCP_EXPECTED_TOOLS": json.dumps(["a_get", "a_list"]),
    "MCP_READ_TOOL": "a_list",
    "MCP_READ_ARGUMENTS": "{}",
}


def load(overrides=None):
    spec = importlib.util.spec_from_file_location("probe_contract", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {**ENV, **(overrides or {})}, clear=False):
        spec.loader.exec_module(module)
    return module


def ok(tools=("a_get", "a_list"), is_error=False):
    """Return a fake rpc() honouring the contract.

    Args:
        tools: the tool names the fake server advertises.
        is_error: whether the read call reports an error result.
    """

    def rpc(method, params=None, authorization=None, url=None, notification=False):
        if authorization != "Bearer real":
            return 401, '{"error":"unauthenticated"}'
        if method == "initialize":
            return 200, json.dumps({"result": {"protocolVersion": "2025-06-18"}})
        if method == "tools/list":
            return 200, json.dumps(
                {"result": {"tools": [{"name": name} for name in tools]}}
            )
        return 200, json.dumps({"result": {"isError": is_error, "content": []}})

    return rpc


class TestProbeContract(unittest.TestCase):
    def test_a_conforming_provider_passes(self):
        module = load()
        with patch.object(module, "rpc", ok()):
            module.main()

    def test_an_endpoint_that_answers_without_a_credential_fails(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            return 200, json.dumps({"result": {"tools": []}})

        with patch.object(module, "rpc", rpc), self.assertRaises(SystemExit):
            module.main()

    def test_an_endpoint_that_accepts_a_wrong_credential_fails(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization is None:
                return 401, "{}"
            return 200, json.dumps({"result": {"tools": [{"name": "a_get"}]}})

        with patch.object(module, "rpc", rpc), self.assertRaises(SystemExit):
            module.main()

    def test_a_bare_401_without_a_json_rpc_body_still_counts_as_refused(self):
        module = load()
        conforming = ok()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization != "Bearer real":
                return 401, "401: Unauthorized"
            return conforming(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()

    def test_a_404_html_page_counts_as_refused(self):
        module = load()
        conforming = ok()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization != "Bearer real":
                return 404, "<!DOCTYPE html><html><body>Not Found</body></html>"
            return conforming(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()

    def test_an_endpoint_that_hands_out_a_session_without_a_credential_fails(self):
        module = load()
        conforming = ok()
        stderr = io.StringIO()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization is None and method == "initialize":
                return 200, json.dumps(
                    {"result": {"protocolVersion": "2025-06-18", "capabilities": {}}}
                )
            return conforming(method, params, authorization)

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("REJECTED", stderr.getvalue())

    def test_a_502_without_a_json_rpc_body_keeps_the_caller_retrying(self):
        module = load()
        stderr = io.StringIO()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            return 502, "<html><body>Bad Gateway</body></html>"

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertNotIn("REJECTED", stderr.getvalue())

    def test_the_unauthenticated_handshake_does_not_leak_its_session(self):
        module = load()
        conforming = ok()
        module.SESSION["id"] = "authenticated-session"

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization != "Bearer real":
                module.SESSION["id"] = "anonymous-session"
                return 401, "401: Unauthorized"
            return conforming(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()
        self.assertEqual(module.SESSION["id"], "authenticated-session")

    def test_a_200_without_a_json_rpc_body_keeps_the_caller_retrying(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            return 200, "<br />Fatal error: uncaught Error"

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertNotIn("REJECTED", stderr.getvalue())

    def test_an_extra_upstream_tool_fails_closed(self):
        module = load()
        stderr = io.StringIO()
        with (
            patch.object(module, "rpc", ok(tools=("a_get", "a_list", "a_delete"))),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("a_delete", stderr.getvalue())

    def test_a_missing_declared_tool_fails(self):
        module = load()
        with (
            patch.object(module, "rpc", ok(tools=("a_get",))),
            self.assertRaises(SystemExit),
        ):
            module.main()

    def test_a_read_call_returning_an_error_result_fails(self):
        module = load()
        stderr = io.StringIO()
        with (
            patch.object(module, "rpc", ok(is_error=True)),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("error result", stderr.getvalue())

    def test_the_read_call_is_skipped_when_none_is_declared(self):
        module = load({"MCP_READ_TOOL": ""})
        calls = []

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            calls.append(method)
            return ok()(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()
        self.assertNotIn("tools/call", calls)

    def test_a_provider_that_has_not_started_keeps_the_caller_retrying(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if method != "tools/call":
                return ok()(method, params, authorization)
            return 502, json.dumps(
                {
                    "error": {
                        "code": -32000,
                        "message": "upstream_error",
                        "data": {"upstream_status": 503},
                    }
                }
            )

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertNotIn("REJECTED", stderr.getvalue())

    def test_a_provider_refusing_the_adapter_credential_fails_closed(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if method != "tools/call":
                return ok()(method, params, authorization)
            return 502, json.dumps(
                {
                    "error": {
                        "code": -32000,
                        "message": "upstream_error",
                        "data": {"upstream_status": 401},
                    }
                }
            )

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("REJECTED", stderr.getvalue())

    def test_the_session_id_is_carried_after_initialize(self):
        module = load()
        module.SESSION["id"] = ""
        seen = []

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            seen.append((method, module.SESSION["id"]))
            if method == "initialize":
                module.SESSION["id"] = "sess-1"
            return ok()(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()
        after_initialize = [
            session for method, session in seen if method == "tools/list"
        ]
        self.assertEqual(
            after_initialize[-1],
            "sess-1",
            "a streamable-HTTP server answers 404 'Invalid session ID' without it",
        )
        self.assertIn(
            "notifications/initialized",
            [method for method, _ in seen],
            "servers built on mcp-go serve no tools until the client confirms",
        )

    def test_an_event_stream_framed_response_is_parsed(self):
        module = load()
        self.assertEqual(
            module.json_body(
                "text/event-stream",
                'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
            ),
            '{"jsonrpc":"2.0","id":1,"result":{}}',
            "streamable HTTP may answer a POST with a stream carrying the same object",
        )
        self.assertEqual(
            module.json_body("application/json", '{"result":{}}'),
            '{"result":{}}',
        )

    def test_a_json_rpc_error_counts_as_a_refusal(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization != "Bearer real":
                return 200, json.dumps(
                    {"jsonrpc": "2.0", "error": {"code": -32603, "message": "no token"}}
                )
            return ok()(method, params, authorization)

        with patch.object(module, "rpc", rpc):
            module.main()

    def test_a_served_response_without_an_error_still_fails(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            if authorization != "Bearer real":
                return 200, json.dumps({"jsonrpc": "2.0", "result": {}})
            return ok()(method, params, authorization)

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("unauthenticated probe answered 200", stderr.getvalue())

    def test_an_unreachable_endpoint_keeps_the_caller_retrying(self):
        module = load()

        def rpc(method, params=None, authorization=None, url=None, notification=False):
            return 0, "unreachable: connection refused"

        with (
            patch.object(module, "rpc", rpc),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertNotIn(
            "REJECTED",
            stderr.getvalue(),
            "a sidecar that has not started yet must not settle the retry loop",
        )


KEY = "k" * 32
TOOLS = ("list_databases", "list_tables", "get_table_schema")

PING_SECONDS = 1
IDLE_SECONDS = 30


class FakeProvider:
    """Serves one SSE MCP surface, guarded by the key in its URL path."""

    def __init__(self, tools=TOOLS, guarded=True, preamble_frames=1, is_error=False):
        """
        Args:
            tools: the tool names ``tools/list`` advertises.
            guarded: whether a wrong path key is refused.
            preamble_frames: comment frames sent before the endpoint event.
            is_error: whether ``tools/call`` reports an error result.
        """
        self.tools = tuple(tools)
        self.guarded = guarded
        self.preamble_frames = preamble_frames
        self.is_error = is_error
        self.sessions: dict[str, queue.Queue] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self):
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/mcp/{KEY}/sse"

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                parts = self.path.strip("/").split("/")
                if len(parts) != 3 or parts[0] != "mcp" or parts[2] != "sse":
                    self.send_error(404)
                    return
                if provider.guarded and parts[1] != KEY:
                    self.send_response(401)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                session_id = f"s{len(provider.sessions)}"
                provider.sessions[session_id] = queue.Queue()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for _ in range(provider.preamble_frames):
                    self._chunk(b": ping\n\n")
                self._chunk(
                    f"event: endpoint\ndata: /mcp/messages/?session_id={session_id}"
                    f"\n\n".encode()
                )
                deadline = time.monotonic() + IDLE_SECONDS
                while time.monotonic() < deadline:
                    try:
                        message = provider.sessions[session_id].get(
                            timeout=PING_SECONDS
                        )
                    except queue.Empty:
                        message = None
                    try:
                        if message is None:
                            self._chunk(b": ping\n\n")
                        else:
                            self._chunk(f"event: message\ndata: {message}\n\n".encode())
                    except OSError:
                        return

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if not parsed.path.startswith("/mcp/messages/"):
                    self.send_error(405)
                    return
                session_id = urllib.parse.parse_qs(parsed.query).get(
                    "session_id", [""]
                )[0]
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

                method = payload.get("method")
                if method == "initialize":
                    result = {"protocolVersion": "2025-06-18", "capabilities": {}}
                elif method == "tools/list":
                    result = {"tools": [{"name": name} for name in provider.tools]}
                else:
                    result = {"isError": provider.is_error, "content": []}
                provider.sessions[session_id].put(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}
                    )
                )

            def _chunk(self, body):
                self.wfile.write(f"{len(body):X}\r\n".encode() + body + b"\r\n")
                self.wfile.flush()

        return Handler


def sse_env(provider, tools=TOOLS, read_tool="list_databases"):
    """Return the probe environment addressing one fake SSE provider.

    Args:
        provider: the FakeProvider to address.
        tools: the tool names the contract declares.
        read_tool: the deterministic read tool, or "" for none.
    """
    return {
        "MCP_URL": provider.url,
        "MCP_TRANSPORT": "sse",
        "MCP_PATH_KEY": KEY,
        "MCP_EXPECTED_TOOLS": json.dumps(sorted(tools)),
        "MCP_READ_TOOL": read_tool,
        "MCP_READ_ARGUMENTS": "{}",
    }


class TestSseSessionProbe(unittest.TestCase):
    def serve(self, **kwargs):
        provider = FakeProvider(**kwargs)
        self.addCleanup(provider.stop)
        return provider

    def test_a_conforming_sse_provider_passes(self):
        provider = self.serve()
        load(sse_env(provider)).main()

    def test_an_extra_upstream_tool_fails_closed(self):
        provider = self.serve(tools=(*TOOLS, "delete_rows"))
        module = load(sse_env(provider, tools=TOOLS))
        with (
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("delete_rows", stderr.getvalue())

    def test_a_read_call_returning_an_error_result_fails(self):
        provider = self.serve(is_error=True)
        module = load(sse_env(provider))
        with (
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("error result", stderr.getvalue())

    def test_an_endpoint_serving_any_path_key_fails(self):
        provider = self.serve(guarded=False)
        module = load(sse_env(provider))
        with (
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("unauthenticated probe answered 200", stderr.getvalue())

    def test_a_long_preamble_does_not_hide_the_endpoint_announcement(self):
        provider = self.serve(preamble_frames=6)
        load(sse_env(provider)).main()

    def test_an_unreachable_stream_keeps_the_caller_retrying(self):
        module = load(
            {
                "MCP_URL": f"http://127.0.0.1:1/mcp/{KEY}/sse",
                "MCP_TRANSPORT": "sse",
                "MCP_PATH_KEY": KEY,
                "MCP_EXPECTED_TOOLS": "[]",
                "MCP_READ_TOOL": "",
                "MCP_READ_ARGUMENTS": "{}",
            }
        )
        with (
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertNotIn("REJECTED", stderr.getvalue())

    def test_a_key_absent_from_the_probed_url_fails(self):
        provider = self.serve()
        module = load({**sse_env(provider), "MCP_PATH_KEY": "z" * 32})
        with (
            contextlib.redirect_stderr(io.StringIO()) as stderr,
            self.assertRaises(SystemExit),
        ):
            module.main()
        self.assertIn("absent from the probed URL", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
