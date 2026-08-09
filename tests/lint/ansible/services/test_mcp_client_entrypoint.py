"""Lint: every MCP client role carries the entrypoint the reconciler includes.

``sys-svc-mcp-reconcile`` iterates the client roles the discovery lookup returns
and includes ``tasks/utils/mcp.yml`` from each. The file name is the contract: a
role that declares a client direction without it aborts every deployment that
happens to include the role, long after the change that broke it.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-client-entrypoint`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_TASKS_MCP

from . import PROJECT_ROOT

_RULE = "mcp-client-entrypoint"
_CLIENT_DIRECTIONS = frozenset({"client", "both"})


def _client_roles() -> list[Path]:
    """Return the role directories whose MCP block declares a client side."""
    roles: list[Path] = []
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() not in _CLIENT_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        roles.append(mcp_path.parent.parent)
    return roles


class TestMcpClientEntrypoint(unittest.TestCase):
    def test_every_client_role_has_the_reconciler_entrypoint(self) -> None:
        missing = [
            f"{role.name}: declares an MCP client direction but has no "
            f"{ROLE_FILE_TASKS_MCP}, so the reconciler's include fails at runtime"
            for role in _client_roles()
            if not (role / ROLE_FILE_TASKS_MCP).is_file()
        ]
        self.assertEqual(
            [],
            missing,
            f"MCP client role(s) without the reconciler entrypoint ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_client_roles(self) -> None:
        self.assertTrue(
            _client_roles(),
            "no role declares an MCP client direction, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
