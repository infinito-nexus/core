"""Filter ``mcp_authorization``: the Authorization header an MCP server wants.

    {{ server | mcp_authorization }}          -> "Bearer <token>"
    {{ server | mcp_authorization(env='X') }} -> "Bearer ${env:X}"

``bearer_token``, ``app_password`` and ``upstream_session`` present the
credential as a bearer. ``basic_auth`` presents ``username:token`` base64
encoded, which cannot reference an environment variable because the encoding
happens before the value is known.

``oidc`` is deliberately absent. It means the call executes as the requesting
end user, and a rendered config carries no caller. Emitting the deployment's
own bearer there would relabel a service account as user delegation, so this
filter refuses it and ``mcp_authorization_is_renderable`` drops the server.
Open WebUI reaches such a server through ``system_oauth`` instead; see
``docs/contributing/design/role/services/mcp-delegation.md``.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

BEARER_AUTHS = frozenset({"bearer_token", "app_password", "upstream_session"})
BASIC_AUTHS = frozenset({"basic_auth"})
DELEGATED_AUTHS = frozenset({"oidc"})

SUPPORTED_AUTHS = BEARER_AUTHS | BASIC_AUTHS


def mcp_authorization(server: Mapping[str, Any], env: str | None = None) -> str:
    """Return the Authorization header value for one discovered MCP server.

    Args:
        server: a MCP_DISCOVERED_SERVERS entry carrying auth, token, owner.
        env: name of the environment variable holding the token. Bearer schemes
            reference it instead of inlining the secret; basic auth ignores it
            because the credential is encoded, not substituted.
    """
    auth = str(server.get("auth") or "")
    token = str(server.get("token") or "")

    if auth in BASIC_AUTHS:
        owner = str(server.get("owner") or "")
        if not owner:
            raise ValueError(
                f"MCP server {server.get('id')!r} declares auth {auth!r} but "
                f"resolves no credential owner. Basic auth would authenticate "
                f"as the empty user and the server would answer 401."
            )
        encoded = base64.b64encode(f"{owner}:{token}".encode()).decode()
        return f"Basic {encoded}"

    if auth in BEARER_AUTHS:
        return f"Bearer ${{env:{env}}}" if env else f"Bearer {token}"

    if auth in DELEGATED_AUTHS:
        raise ValueError(
            f"MCP server {server.get('id')!r} declares auth {auth!r}, which "
            f"executes as the requesting user. A rendered config carries no "
            f"caller, so presenting the deployment's own bearer here would be "
            f"a service account wearing a user's name. Filter these servers "
            f"out with mcp_renderable_servers."
        )

    raise ValueError(
        f"MCP server {server.get('id')!r} declares auth {auth!r}, which no "
        f"client renderer can present. Supported: {sorted(SUPPORTED_AUTHS)}."
    )


def mcp_authorization_is_renderable(server: Mapping[str, Any]) -> bool:
    """Return whether a client can present this server's auth scheme at all."""
    return str(server.get("auth") or "") in SUPPORTED_AUTHS


def mcp_renderable_servers(servers: Any) -> list:
    """Return only the servers whose auth a client can present.

    Args:
        servers: a MCP_DISCOVERED_SERVERS-shaped sequence, or None.
    """
    return [s for s in servers or [] if mcp_authorization_is_renderable(s)]


class FilterModule:
    def filters(self):
        return {
            "mcp_authorization": mcp_authorization,
            "mcp_authorization_is_renderable": mcp_authorization_is_renderable,
            "mcp_renderable_servers": mcp_renderable_servers,
        }
