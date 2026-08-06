"""Filter ``mcp_group_members``: who may reach each MCP tool server.

    {{ lookup('users') | mcp_group_members(MCP_DISCOVERED_SERVERS) }}
    -> {"web-app-baserow": ["alice"], "web-app-zammad": []}

A client cannot rely on the OIDC groups claim alone to revoke access: Open
WebUI drops a stale membership only while the claim is non-empty, so a user
who loses their last group keeps it until a later login carries one. The
deployment therefore reconciles each group's member list explicitly, and an
empty list is a real instruction to empty the group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.rbac.scoped import members_with_role

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

MCP_ROLE = "mcp"


def mcp_group_members(
    users: Mapping[str, Any] | None,
    servers: Sequence[Mapping[str, Any]] | None,
) -> dict[str, list[str]]:
    """Return the usernames granted ``mcp`` on each discovered server.

    Args:
        users: the merged users mapping.
        servers: the selected ``MCP_DISCOVERED_SERVERS`` entries.
    """
    return {
        server_id: members_with_role(users, server_id, MCP_ROLE)
        for server_id in (str(s.get("id") or "") for s in servers or [] if s.get("id"))
    }


class FilterModule:
    def filters(self):
        return {"mcp_group_members": mcp_group_members}
