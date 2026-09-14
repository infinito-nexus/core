"""Lint: a served MCP surface has an application-scoped role to grant.

Every client grant resolves to the group named after one role: the provider's
own ``mcp`` RBAC role. A provider that serves without declaring it leaves the
client nothing to scope access to, and the fallback is not "nobody" — Open WebUI
reads an empty grant as every administrator, which is wider than the group was
ever meant to be.

The role has to be application-scoped rather than a shared ``mcp`` name, which
``utils/roles/rbac/scoped.py`` enforces from the other side: a role listed in
``APPLICATION_SCOPED_ROLES`` grants nothing when declared unscoped, so the
declaration here is what a user's ``application_roles`` entry points at.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-server-rbac-role`` in the head of the role's ``meta/mcp.yml``.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_RBAC
from utils.roles.rbac.scoped import MCP_LEGACY_ROLE

from . import PROJECT_ROOT

_RULE = "mcp-server-rbac-role"
_SERVER_DIRECTIONS = frozenset({"server", "both"})


def _server_roles() -> list[str]:
    """Return the roles that serve MCP to a client."""
    roles: list[str] = []
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() not in _SERVER_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        roles.append(mcp_path.parent.parent.name)
    return roles


def _declares_mcp_role(role: str) -> bool:
    rbac = load_yaml_any(
        str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_RBAC), default_if_missing={}
    )
    declared = (rbac or {}).get("roles")
    return isinstance(declared, Mapping) and MCP_LEGACY_ROLE in declared


class TestMcpServerRbacRole(unittest.TestCase):
    def test_every_served_surface_declares_its_own_mcp_role(self) -> None:
        missing = [
            f"{role}: serves MCP but declares no '{MCP_LEGACY_ROLE}' role in "
            f"{ROLE_FILE_META_RBAC}, so a client grant has no group to name and "
            f"an empty grant reads as every administrator"
            for role in _server_roles()
            if not _declares_mcp_role(role)
        ]
        self.assertEqual(
            [],
            missing,
            f"served MCP surface(s) without an application-scoped role "
            f"({len(missing)}):\n" + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_served_surfaces(self) -> None:
        self.assertTrue(
            _server_roles(),
            "no role serves MCP, so the rule would pass vacuously; check that "
            "the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
