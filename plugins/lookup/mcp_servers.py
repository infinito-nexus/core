"""Lookup ``mcp_servers``: the MCP servers a client role can connect to.

    {{ lookup('mcp_servers') }}

Returns one entry per deployed MCP server role the administrator holds a
token for, shaped for the client renderers ``mcp_authorization`` and
``mcp_tool_server_connections``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def build_mcp_servers(
    servers: Sequence[Mapping[str, Any]] | None,
    administrator: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the connectable MCP servers among the discovered ones.

    Args:
        servers: ``roles_with_service('mcp', direction='server')`` entries.
        administrator: the administrator user, carrying tokens and username.
    """
    tokens = administrator.get("tokens") or {}
    username = administrator.get("username")
    connectable = []
    for server in servers or []:
        server_id = str(server.get("id") or "")
        token = str(tokens.get(server_id) or "").strip()
        endpoint = server.get("endpoint") or {}
        port = endpoint.get("port")
        path = endpoint.get("path")
        if not server_id or not token or not port or not path:
            continue
        connectable.append(
            {
                "id": server_id,
                "url": f"http://{endpoint.get('service_key')}:{port}{path}",
                "token": token,
                "auth": server.get("auth"),
                "username": username,
                "transport": str(server.get("transport") or "").replace("_", "-"),
            }
        )
    return connectable


class LookupModule(LookupBase):
    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError(
                "mcp_servers: expected no terms — lookup('mcp_servers')"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        servers = lookup_loader.get(
            "roles_with_service", loader=self._loader, templar=templar
        ).run(["mcp"], variables=vars_, direction="server", scope="all")[0]
        administrator = lookup_loader.get(
            "users", loader=self._loader, templar=templar
        ).run(["administrator"], variables=vars_)[0]

        return [build_mcp_servers(servers, administrator)]
