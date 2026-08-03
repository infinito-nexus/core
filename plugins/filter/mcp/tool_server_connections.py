"""Filter ``mcp_tool_server_connections``: Open WebUI tool-server entries.

    {{ MCP_DISCOVERED_SERVERS | mcp_tool_server_connections }}

Open WebUI reads ``TOOL_SERVER_CONNECTIONS`` as a JSON list validated by its
``ToolServerConnection`` model. For ``type: mcp`` it connects to ``url``
directly, so the discovered endpoint URL goes there whole and ``path`` stays
empty.

Entries render disabled. An empty ``config.access_grants`` is not "nobody":
``has_connection_access`` reads it as every administrator, which is wider than
the role's ``mcp`` group and would apply on every start, because
``ENABLE_PERSISTENT_CONFIG=false`` makes this env authoritative again after a
restart. ``tasks/01_mcp.yml`` resolves the group, whose Open WebUI id exists
only at runtime, and enables the entry in the same write. Until it does, the
tool server is not served at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

TOOL_SERVER_TYPE = "mcp"
AUTH_TYPE_BEARER = "bearer"

BEARER_PRESENTABLE_AUTHS = frozenset(
    {"bearer_token", "app_password", "upstream_session", "oidc"}
)


def mcp_tool_server_connections(servers: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Return one Open WebUI tool-server connection per discovered MCP server.

    Servers whose auth scheme Open WebUI cannot present are skipped: its
    ToolServerConnection accepts bearer, session, system_oauth and oauth_2.1,
    so a basic-auth endpoint would be registered with an unusable credential.
    """
    connections = []
    for server in servers or []:
        server_id = str(server.get("id", "")).strip()
        url = str(server.get("url", "")).strip()
        if not server_id or not url:
            continue
        if str(server.get("auth") or "") not in BEARER_PRESENTABLE_AUTHS:
            continue
        connections.append(
            {
                "url": url,
                "path": "",
                "type": TOOL_SERVER_TYPE,
                "auth_type": AUTH_TYPE_BEARER,
                "key": str(server.get("token", "")),
                "config": {"enable": False, "access_grants": []},
                "info": {"id": server_id, "name": server_id},
            }
        )
    return connections


class FilterModule:
    def filters(self):
        return {"mcp_tool_server_connections": mcp_tool_server_connections}
