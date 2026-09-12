"""How the contract probe tells upstream drift apart from a policy mismatch."""

from __future__ import annotations

import importlib.util
import json
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "roles/test-e2e-cli/files/shared/mcp/contract.py"

BASE_ENV = {
    "MCP_URL": "http://example:8080/mcp",
    "MCP_TRANSPORT": "streamable_http",
    "MCP_AUTH_HEADER": "Bearer token",
}


def load(*, allowlist, serves):
    """Import the probe with one contract's expectations in the environment."""
    spec = importlib.util.spec_from_file_location("probe_contract", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    env = {
        **BASE_ENV,
        "MCP_EXPECTED_TOOLS": json.dumps(allowlist),
        "MCP_UPSTREAM_SERVES": json.dumps(serves),
    }
    with patch.dict("os.environ", env, clear=False):
        spec.loader.exec_module(module)
    return module


class TestAssertSurface(unittest.TestCase):
    def test_a_matching_surface_passes(self) -> None:
        module = load(allowlist=["read_post"], serves=[])
        module.assert_surface(["read_post"])

    def test_a_policy_mismatch_names_the_contract(self) -> None:
        module = load(allowlist=["read_post"], serves=[])
        with self.assertRaises(SystemExit):
            module.assert_surface(["read_post", "delete_post"])

    def test_upstream_drift_is_reported_before_policy(self) -> None:
        """The recorded surface is stale, so the reader must be told the vendor
        changed something, not that our own contract is wrong."""
        module = load(allowlist=["read_post"], serves=["read_post", "delete_post"])
        with self.assertRaises(SystemExit):
            module.assert_surface(["read_post", "delete_post", "archive_channel"])

    def test_a_recorded_difference_still_fails_policy(self) -> None:
        module = load(allowlist=["read_post"], serves=["read_post", "delete_post"])
        with self.assertRaises(SystemExit):
            module.assert_surface(["read_post", "delete_post"])

    def test_an_unrecorded_surface_is_judged_on_policy_alone(self) -> None:
        module = load(allowlist=["read_post"], serves=[])
        module.assert_surface(["read_post"])
        with self.assertRaises(SystemExit):
            module.assert_surface(["read_post", "delete_post"])


if __name__ == "__main__":
    unittest.main()
