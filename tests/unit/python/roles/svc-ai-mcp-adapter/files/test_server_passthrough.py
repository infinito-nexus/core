"""The adapter's behaviour when the upstream it fronts already speaks MCP."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from typing import ClassVar
from unittest.mock import patch

from . import PROJECT_ROOT

FILES_DIR = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python"
MODULE_PATH = FILES_DIR / "server.py"

TOOLS: dict[str, dict] = {
    "read_post": {"mutating": False},
    "search_users": {"mutating": False},
}

LIMITS: dict[str, int] = {
    "request_bytes": 4096,
    "response_bytes": 1048576,
    "timeout_seconds": 15,
    "concurrent_requests": 4,
    "page_size": 100,
    "result_items": 5,
    "stream_seconds": 300,
}


def load(tools=None, *, mutating=False):
    """Import the adapter server against an MCP-kind contract."""
    spec = importlib.util.spec_from_file_location("adapter_server_mcp", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(FILES_DIR))
    try:
        import policy

        payload = tools if tools is not None else TOOLS
        contract = {
            "upstream_kind": "mcp",
            "provider": "web-app-example",
            "upstream_url": "http://example:8065/plugins/x/mcp",
            "auth_subject": "service_account",
            "tools": payload,
            "limits": LIMITS,
            "mutating_tools_enabled": mutating,
            "schema_sha256": policy.schema_digest(payload),
        }
        env = {"ADAPTER_CONTRACT": json.dumps(contract), "ADAPTER_BEARER": "real"}
        with patch.dict("os.environ", env, clear=False):
            spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(FILES_DIR))
    return module


class FakeResponse(io.BytesIO):
    """Stands in for the object urlopen returns, headers included."""

    def __init__(self, body: bytes, content_type: str, status: int):
        super().__init__(body)
        self.headers = {"Content-Type": content_type, "Mcp-Session-Id": "sess-1"}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestPassthroughDispatch(unittest.TestCase):
    MODULE: ClassVar = load()

    def test_the_contract_selects_the_mcp_transport(self) -> None:
        self.assertTrue(self.MODULE.UPSTREAM_IS_MCP)

    def test_only_contracted_tools_are_advertised(self) -> None:
        listed = self.MODULE.dispatch({"method": "tools/list"}, "consumer", "cid")
        self.assertEqual(
            sorted(tool["name"] for tool in listed["tools"]),
            ["read_post", "search_users"],
        )

    def test_a_call_is_forwarded_as_jsonrpc_by_name(self) -> None:
        seen = {"methods": [], "sessions": []}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            body = json.loads(request.data.decode())
            seen["methods"].append(body.get("method"))
            seen["sessions"].append(request.get_header("Mcp-session-id"))
            seen["body"] = body
            return FakeResponse(
                json.dumps(
                    {"jsonrpc": "2.0", "id": "1", "result": {"ok": True}}
                ).encode(),
                content_type="application/json",
                status=200,
            )

        with patch.object(self.MODULE.urllib.request, "urlopen", fake_urlopen):
            self.MODULE.dispatch(
                {
                    "method": "tools/call",
                    "params": {"name": "read_post", "arguments": {"id": "7"}},
                },
                "consumer",
                "cid",
            )

        self.assertEqual(seen["url"], "http://example:8065/plugins/x/mcp")
        self.assertEqual(
            seen["methods"], ["initialize", "notifications/initialized", "tools/call"]
        )
        self.assertEqual(seen["sessions"][-1], "sess-1")
        self.assertEqual(seen["body"]["method"], "tools/call")
        self.assertEqual(seen["body"]["params"]["name"], "read_post")
        self.assertEqual(seen["body"]["params"]["arguments"], {"id": "7"})

    def test_an_unlisted_tool_never_reaches_the_upstream(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("the upstream must not be contacted")

        with (
            patch.object(self.MODULE.urllib.request, "urlopen", fail_if_called),
            self.assertRaises(PermissionError),
        ):
            self.MODULE.dispatch(
                {"method": "tools/call", "params": {"name": "delete_post"}},
                "consumer",
                "cid",
            )

    def test_an_upstream_error_object_carries_the_real_status(self) -> None:
        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            body = json.loads(request.data.decode())
            if body.get("method") != "tools/call":
                return FakeResponse(
                    json.dumps({"jsonrpc": "2.0", "id": "1", "result": {}}).encode(),
                    content_type="application/json",
                    status=200,
                )
            return FakeResponse(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "1",
                        "error": {"code": -32000, "message": "nope"},
                    }
                ).encode(),
                content_type="application/json",
                status=200,
            )

        with (
            patch.object(self.MODULE.urllib.request, "urlopen", fake_urlopen),
            self.assertRaises(ValueError) as caught,
        ):
            self.MODULE.dispatch(
                {"method": "tools/call", "params": {"name": "read_post"}},
                "consumer",
                "cid",
            )
        self.assertEqual(self.MODULE.upstream_status(caught.exception), 200)


class TestEventStreamDecoding(unittest.TestCase):
    MODULE: ClassVar = load()

    def test_a_single_sse_frame_is_unwrapped(self) -> None:
        body = b'event: message\ndata: {"jsonrpc":"2.0","id":"1","result":{"ok":1}}\n\n'
        parsed = self.MODULE.decode_jsonrpc(body, "text/event-stream")
        self.assertEqual(parsed["result"], {"ok": 1})

    def test_a_stream_without_a_data_frame_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            self.MODULE.decode_jsonrpc(b"event: ping\n\n", "text/event-stream")

    def test_a_plain_json_body_is_parsed_directly(self) -> None:
        parsed = self.MODULE.decode_jsonrpc(b'{"result": 2}', "application/json")
        self.assertEqual(parsed["result"], 2)


if __name__ == "__main__":
    unittest.main()
