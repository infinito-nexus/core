"""Every shipped tool contract survives the loader the sidecar runs at startup.

`svc-ai-mcp-adapter` validates its contract while importing, and a rejection
kills the process. Compose then reports a container that never turns healthy,
which surfaces an hour into a deploy as a failing probe rather than as the
metadata edit it is -- and `server.py` answers `/health` unconditionally, so a
contract that loads but advertises the wrong set fails even later, at the first
`tools/call`.

Nothing else runs a shipped `roles/*/files/mcp/tools.json` through that path:
the sibling suites here build synthetic contracts, `test_mcp_contract_digest.py`
recomputes the hash without loading, and `test_mcp_tool_surface.py` compares
YAML to YAML. This file closes that gap by assembling the contract the role's
own `vars/main.yml` assembles and handing it to the real `load_contract` /
`load_mcp_contract`, so a limit that stopped being a positive integer, a
`mutating: true` tool in a read-only surface, an unspeakable upstream transport
or a stale digest fails here in a second instead of on a deployed host.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

FILES_DIR = PROJECT_ROOT / "roles/svc-ai-mcp-adapter/files/python"

MCP_UPSTREAM_ADAPTER_TYPES = frozenset({"mcp_passthrough"})


def load_adapter():
    """Import the adapter's policy layer the way the image lays it out.

    `passthrough` imports `policy` as a sibling, so its own directory has to be
    importable before the module body runs.
    """
    spec = importlib.util.spec_from_file_location(
        "shipped_passthrough", FILES_DIR / "passthrough.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(FILES_DIR))
    try:
        spec.loader.exec_module(module)
        import policy as policy_module
    finally:
        sys.path.remove(str(FILES_DIR))
    return module, policy_module


passthrough, policy = load_adapter()


def shipped() -> list[tuple[str, dict, dict]]:
    """Return `(role, mcp block, tool mapping)` for every shipped contract."""
    found = []
    for spec in sorted(PROJECT_ROOT.glob("roles/*/files/mcp/tools.json")):
        role = spec.parent.parent.parent.name
        block = load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MCP)
        found.append((role, block, json.loads(read_text(str(spec)))))
    return found


def contract_of(role: str, block: dict, tools: dict) -> str:
    """Return the `ADAPTER_CONTRACT` the role's compose template hands the sidecar.

    Args:
        role: the role directory name.
        block: the role's `meta/mcp.yml`.
        tools: the shipped tool mapping.
    """
    adapter = block.get("adapter") or {}
    contract = {
        "provider": role,
        "upstream_url": f"http://{role}:8080{adapter.get('upstream_path', '/')}",
        "auth_subject": block.get("auth_subject"),
        "mutating_tools_enabled": bool(
            (block.get("tools") or {}).get("mutating_tools_enabled")
        ),
        "tools": tools,
        "limits": block["limits"],
        "schema_sha256": (block.get("tools") or {}).get("schema_sha256"),
    }
    if adapter.get("type") in MCP_UPSTREAM_ADAPTER_TYPES:
        contract["upstream_kind"] = passthrough.KIND_MCP
        contract["upstream_transport"] = adapter.get("upstream_transport")
    return json.dumps(contract)


def load(block: dict, raw: str) -> dict:
    """Return the contract as the sidecar loads it.

    Args:
        block: the role's `meta/mcp.yml`.
        raw: the serialised contract.
    """
    adapter_type = (block.get("adapter") or {}).get("type")
    if adapter_type in MCP_UPSTREAM_ADAPTER_TYPES:
        return passthrough.load_mcp_contract(raw)
    return policy.load_contract(raw)


class TestShippedContracts(unittest.TestCase):
    def test_every_shipped_contract_loads(self):
        for role, block, tools in shipped():
            with self.subTest(role=role):
                load(block, contract_of(role, block, tools))

    def test_every_shipped_contract_matches_its_pinned_digest(self):
        for role, block, tools in shipped():
            with self.subTest(role=role):
                policy.assert_no_drift(load(block, contract_of(role, block, tools)))

    def test_the_advertised_tools_are_the_declared_allowlist(self):
        for role, block, tools in shipped():
            with self.subTest(role=role):
                loaded = load(block, contract_of(role, block, tools))
                self.assertEqual(
                    sorted((block.get("tools") or {}).get("allowlist") or []),
                    policy.listed_tools(loaded),
                    f"{role} advertises a set its meta does not declare",
                )

    def test_a_read_only_surface_ships_no_mutating_tool(self):
        for role, block, tools in shipped():
            if (block.get("tools") or {}).get("mutating_tools_enabled"):
                continue
            with self.subTest(role=role):
                mutating = sorted(
                    name for name, spec in tools.items() if spec.get("mutating")
                )
                self.assertEqual(
                    [],
                    mutating,
                    f"{role} withholds mutations yet ships {mutating}, which the "
                    f"loader refuses at startup",
                )

    def test_the_scan_finds_contracts(self):
        self.assertTrue(
            shipped(),
            "no shipped contract was read, so every assertion here would pass "
            "vacuously",
        )


if __name__ == "__main__":
    unittest.main()
