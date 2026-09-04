"""Filter ``mcp_group_members``: who may reach each MCP tool server.

    {{ lookup('users') | mcp_group_members(MCP_DISCOVERED_SERVERS, 'mcp-reader') }}
    -> {"web-app-baserow": [{"username": "alice", "email": "alice@example.org"}],
        "web-app-zammad": []}

A client cannot rely on the OIDC groups claim alone to revoke access: Open
WebUI drops a stale membership only while the claim is non-empty, so a user
who loses their last group keeps it until a later login carries one. The
deployment therefore reconciles each group's member list explicitly, and an
empty list is a real instruction to empty the group.

Both identifiers are emitted because the reconciler matches against accounts
Open WebUI created from an OIDC claim, whose display name need not be the
username. The email is the only field both sides agree on exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.rbac.scoped import MCP_ROLES, members_with_role

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _identify(users: Mapping[str, Any] | None, username: str) -> dict[str, str]:
    for key, config in (users or {}).items():
        cfg = config or {}
        if str(cfg.get("username", key)) == username:
            return {"username": username, "email": str(cfg.get("email") or "")}
    return {"username": username, "email": ""}


def mcp_group_members(
    users: Mapping[str, Any] | None,
    servers: Sequence[Mapping[str, Any]] | None,
    role: str,
) -> dict[str, list[dict[str, str]]]:
    """Return the users granted each MCP role on each discovered server.

    Args:
        users: the merged users mapping.
        servers: the selected ``MCP_DISCOVERED_SERVERS`` entries.
        role: the MCP grant to resolve.
    """
    if role not in MCP_ROLES:
        raise ValueError(
            f"mcp_group_members: unknown role {role!r}; "
            f"expected one of {list(MCP_ROLES)}"
        )
    return {
        server_id: [
            _identify(users, username)
            for username in members_with_role(users, server_id, role)
        ]
        for server_id in (str(s.get("id") or "") for s in servers or [] if s.get("id"))
    }


class FilterModule:
    def filters(self):
        return {"mcp_group_members": mcp_group_members}
