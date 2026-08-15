"""Filter ``mcp_tool_server_connections``: Open WebUI tool-server entries.

    {{ MCP_DISCOVERED_SERVERS | mcp_tool_server_connections }}

Open WebUI reads ``TOOL_SERVER_CONNECTIONS`` as a JSON list validated by its
``ToolServerConnection`` model. For ``type: mcp`` it connects to ``url``
directly, so the discovered endpoint URL goes there whole and ``path`` stays
empty.

An entry renders disabled until its group id is known. An empty
``config.access_grants`` is not "nobody": ``has_connection_access`` reads it as
every administrator, which is wider than the role's ``mcp`` group and would
apply on every start, because ``ENABLE_PERSISTENT_CONFIG=false`` makes this env
authoritative again after a restart.

The group id exists only once Open WebUI has minted it, so the first deploy
renders the entry disabled, ``tasks/utils/mcp.yml`` resolves the group through the
API and persists the id, and every later render carries the grant in the env
itself. That is what makes a bare container restart converge: the env it reads
on start already says who may reach the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

TOOL_SERVER_TYPE = "mcp"
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_SYSTEM_OAUTH = "system_oauth"

BEARER_PRESENTABLE_AUTHS = frozenset(
    {"bearer_token", "app_password", "upstream_session"}
)
DELEGATED_AUTHS = frozenset({"oidc"})


def mcp_tool_server_connections(
    servers: Sequence[Mapping[str, Any]],
    group_ids: Mapping[str, str] | None = None,
) -> list[dict]:
    """Return one Open WebUI tool-server connection per discovered MCP server.

    Args:
        servers: the selected ``MCP_DISCOVERED_SERVERS`` entries.
        group_ids: Open WebUI group id per provider ``application_id``, as
            resolved and persisted by an earlier deploy. A server without one
            renders disabled and ungranted.

    Servers whose auth scheme Open WebUI cannot present are skipped: its
    ToolServerConnection accepts bearer, session, system_oauth and oauth_2.1,
    so a basic-auth endpoint would be registered with an unusable credential.

    An ``oidc`` server carries no deployment key. ``system_oauth`` makes Open
    WebUI resolve the requesting user's own token per request, which is the one
    path where the declared ``auth_subject: user`` is true.
    """
    known = group_ids or {}
    connections = []
    for server in servers or []:
        server_id = str(server.get("id", "")).strip()
        url = str(server.get("url", "")).strip()
        if not server_id or not url:
            continue
        auth = str(server.get("auth") or "")
        if auth in DELEGATED_AUTHS:
            auth_type, key = AUTH_TYPE_SYSTEM_OAUTH, ""
        elif auth in BEARER_PRESENTABLE_AUTHS:
            auth_type, key = AUTH_TYPE_BEARER, str(server.get("token", ""))
        else:
            continue
        group_id = str(known.get(server_id) or "").strip()
        grants = (
            [
                {
                    "principal_type": "group",
                    "principal_id": group_id,
                    "permission": "read",
                }
            ]
            if group_id
            else []
        )
        connections.append(
            {
                "url": url,
                "path": "",
                "type": TOOL_SERVER_TYPE,
                "auth_type": auth_type,
                "key": key,
                "config": {"enable": bool(group_id), "access_grants": grants},
                "info": {"id": server_id, "name": server_id},
            }
        )
    return connections


class FilterModule:
    def filters(self):
        return {"mcp_tool_server_connections": mcp_tool_server_connections}
