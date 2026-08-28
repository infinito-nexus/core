"""Lint: signing in to an MCP client does not by itself grant its MCP surface.

An MCP client holds credentials the deployment issued, not the caller's own, so
whoever reaches its UI reaches every provider that client is registered with,
under an identity that is not theirs. None of these upstreams offers a tested
per-server user authorization boundary, so the boundary has to be the gate in
front of them: the connection is restricted to an administrator and to the
application's own ``mcp`` group, never offered to every account that happens to
have a login.

An oauth2 gate with no ``allowed_groups`` admits every authenticated user in the
realm, which is exactly the failure this rule exists for — ``web-app-n8n``
shipped that way while declaring an ``mcp`` role nothing consulted.

Two relations per client role whose gate is an oauth2 proxy:

* the gate names ``allowed_groups`` at all;
* every group it names is scoped to that role's own ``application_id``, so a
  group belonging to another application cannot open this one.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-client-gate-scoped`` in the head of the role's
  ``meta/mcp.yml``, together with the per-server boundary that replaces it.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "mcp-client-gate-scoped"
_CLIENT_DIRECTIONS = frozenset({"client", "both"})


def _gated_client_roles() -> dict[str, Mapping]:
    """Return ``{role: sso block}`` for MCP clients standing behind an oauth2 gate."""
    roles: dict[str, Mapping] = {}
    for mcp_path in sorted(Path(PROJECT_ROOT, "roles").glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() not in _CLIENT_DIRECTIONS:
            continue
        if is_suppressed_in_head(read_text(str(mcp_path)).splitlines(), _RULE):
            continue
        role_dir = mcp_path.parent.parent
        services = load_yaml_any(
            str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        sso = (services or {}).get("sso")
        if not isinstance(sso, Mapping):
            continue
        if str(sso.get("flavor") or "").strip() != "oauth2":
            continue
        roles[role_dir.name] = sso
    return roles


def _allowed_groups(sso: Mapping) -> list[str]:
    oauth2 = sso.get("oauth2")
    if not isinstance(oauth2, Mapping):
        return []
    groups = oauth2.get("allowed_groups")
    return [str(g) for g in groups] if isinstance(groups, list) else []


class TestMcpClientGateScoped(unittest.TestCase):
    def test_every_gated_client_restricts_its_groups(self) -> None:
        open_gates = [
            f"{role}: its oauth2 gate names no allowed_groups, so every "
            f"authenticated account in the realm reaches an MCP client that "
            f"acts with the deployment's provider credentials"
            for role, sso in sorted(_gated_client_roles().items())
            if not _allowed_groups(sso)
        ]
        self.assertEqual(
            [],
            open_gates,
            f"MCP client(s) behind an unrestricted gate ({len(open_gates)}):\n"
            + "\n".join(f"  - {g}" for g in open_gates),
        )

    def test_every_allowed_group_is_application_scoped(self) -> None:
        foreign = []
        for role, sso in sorted(_gated_client_roles().items()):
            for group in _allowed_groups(sso):
                if (
                    f"application_id='{role}'" in group
                    or f'application_id="{role}"' in group
                ):
                    continue
                foreign.append(
                    f"{role}: allows '{group}', which is not scoped to this "
                    f"role's own application_id, so another application's "
                    f"membership opens this client"
                )
        self.assertEqual(
            [],
            foreign,
            "MCP client(s) allowing a foreign group:\n"
            + "\n".join(f"  - {f}" for f in foreign),
        )

    def test_the_scan_finds_gated_clients(self) -> None:
        self.assertTrue(
            _gated_client_roles(),
            "no MCP client role sits behind an oauth2 gate, so both rules "
            "would pass vacuously; check that the scan still reads the right "
            "topic",
        )


if __name__ == "__main__":
    unittest.main()
