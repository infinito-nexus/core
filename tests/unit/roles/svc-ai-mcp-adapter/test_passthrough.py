"""Unit tests for the adapter's policy layer over an MCP-speaking upstream."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from typing import ClassVar

from . import PROJECT_ROOT

FILES_DIR = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files"
MODULE_PATH = FILES_DIR / "passthrough.py"

LIMITS: dict[str, int] = {
    "request_bytes": 64,
    "response_bytes": 1048576,
    "timeout_seconds": 15,
    "concurrent_requests": 4,
    "page_size": 100,
    "result_items": 5,
    "stream_seconds": 300,
}


def load():
    """Import the passthrough layer the way the image lays it out.

    It imports ``policy`` as a sibling, so its own directory has to be
    importable before the module body runs.
    """
    spec = importlib.util.spec_from_file_location("adapter_passthrough", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(FILES_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(FILES_DIR))
    return module


passthrough = load()
sys.path.insert(0, str(FILES_DIR))
import policy  # noqa: E402  sibling module, importable only via FILES_DIR

sys.path.remove(str(FILES_DIR))


def contract(tools, *, mutating=False, kind="mcp"):
    body = {
        "upstream_kind": kind,
        "provider": "web-app-example",
        "upstream_url": "http://example:8065/mcp",
        "tools": tools,
        "limits": LIMITS,
        "mutating_tools_enabled": mutating,
    }
    body["schema_sha256"] = policy.schema_digest(tools)
    return body


READ_TOOLS: dict[str, dict] = {
    "read_post": {"mutating": False},
    "search_users": {"mutating": False},
}


class TestContractKind(unittest.TestCase):
    def test_an_undeclared_kind_is_refused(self) -> None:
        with self.assertRaises(policy.ContractError):
            passthrough.contract_kind({"provider": "x"})

    def test_a_rest_contract_is_not_loaded_as_mcp(self) -> None:
        raw = json.dumps(contract(READ_TOOLS, kind="rest"))
        with self.assertRaises(policy.ContractError):
            passthrough.load_mcp_contract(raw)


class TestRouting(unittest.TestCase):
    def test_a_contract_without_the_key_routes_to_rest(self) -> None:
        legacy = {"provider": "x", "tools": {"a": {"method": "GET", "path": "/a"}}}
        self.assertFalse(passthrough.declares_mcp_upstream(json.dumps(legacy)))

    def test_an_mcp_contract_routes_to_passthrough(self) -> None:
        self.assertTrue(
            passthrough.declares_mcp_upstream(json.dumps(contract(READ_TOOLS)))
        )

    def test_unparseable_input_routes_to_rest_rather_than_raising(self) -> None:
        self.assertFalse(passthrough.declares_mcp_upstream("{not json"))


class TestContractLoading(unittest.TestCase):
    def test_a_read_only_contract_loads(self) -> None:
        loaded = passthrough.load_mcp_contract(json.dumps(contract(READ_TOOLS)))
        self.assertEqual(sorted(loaded["tools"]), ["read_post", "search_users"])

    def test_a_tool_without_a_mutating_flag_is_refused(self) -> None:
        raw = json.dumps(contract({"read_post": {}}))
        with self.assertRaises(policy.ContractError):
            passthrough.load_mcp_contract(raw)

    def test_a_mutating_tool_is_refused_while_mutations_are_off(self) -> None:
        raw = json.dumps(contract({"delete_post": {"mutating": True}}))
        with self.assertRaises(policy.ContractError):
            passthrough.load_mcp_contract(raw)

    def test_a_mutating_tool_loads_once_mutations_are_enabled(self) -> None:
        raw = json.dumps(contract({"delete_post": {"mutating": True}}, mutating=True))
        self.assertIn("delete_post", passthrough.load_mcp_contract(raw)["tools"])


class TestCallAuthorization(unittest.TestCase):
    CONTRACT: ClassVar[dict] = contract(READ_TOOLS)

    def test_a_listed_tool_is_forwarded_by_name(self) -> None:
        self.assertEqual(
            passthrough.authorize_mcp_call(self.CONTRACT, "read_post", {}), "read_post"
        )

    def test_an_unlisted_tool_is_refused_even_though_upstream_serves_it(self) -> None:
        with self.assertRaises(PermissionError) as caught:
            passthrough.authorize_mcp_call(self.CONTRACT, "delete_post", {})
        self.assertIn(policy.DENY_UNKNOWN_TOOL, str(caught.exception))

    def test_an_oversized_argument_payload_is_refused(self) -> None:
        with self.assertRaises(PermissionError) as caught:
            passthrough.authorize_mcp_call(self.CONTRACT, "read_post", {"q": "x" * 200})
        self.assertIn(policy.DENY_REQUEST_TOO_LARGE, str(caught.exception))

    def test_a_mutating_tool_is_refused_at_call_time_when_disabled(self) -> None:
        loaded = contract({"delete_post": {"mutating": True}}, mutating=True)
        loaded["mutating_tools_enabled"] = False
        with self.assertRaises(PermissionError) as caught:
            passthrough.authorize_mcp_call(loaded, "delete_post", {})
        self.assertIn(policy.DENY_MUTATION, str(caught.exception))


class TestUpstreamSurface(unittest.TestCase):
    CONTRACT: ClassVar[dict] = contract(READ_TOOLS)
    SERVED: ClassVar[list] = [
        {"name": "read_post"},
        {"name": "search_users"},
        {"name": "delete_post"},
        {"name": "archive_channel"},
    ]

    def test_only_contracted_tools_are_advertised(self) -> None:
        kept = passthrough.filter_upstream_tools(self.CONTRACT, self.SERVED)
        self.assertEqual([t["name"] for t in kept], ["read_post", "search_users"])

    def test_upstream_growth_is_reported_not_silently_filtered(self) -> None:
        self.assertEqual(
            passthrough.undeclared_upstream_tools(self.CONTRACT, self.SERVED),
            ["archive_channel", "delete_post"],
        )

    def test_a_contract_tool_the_upstream_dropped_is_reported(self) -> None:
        self.assertEqual(
            passthrough.missing_upstream_tools(self.CONTRACT, [{"name": "read_post"}]),
            ["search_users"],
        )


if __name__ == "__main__":
    unittest.main()
