"""Vocabulary of the ``services.mcp`` block in ``meta/services.yml``.

A role with an MCP surface declares one ``mcp:`` service entry. The block
carries the standard consumer flags (``enabled``/``shared``/``bond``) plus
the MCP-specific fields validated by
``tests/lint/ansible/services/test_mcp_schema.py`` and consumed by
``plugins/lookup/roles_with_service.py`` (``direction=...`` calls).

Field vocabulary (see ``docs/contributing/design/role/services/mcp.md``):

* ``direction``:      whether the role exposes MCP, consumes it, or both.
* ``transport``:      wire protocol of the endpoint.
* ``exposure``:       who may reach the endpoint.
* ``auth``:           authentication scheme guarding the endpoint.
* ``auth_subject``:   identity MCP calls execute as.
* ``implementation``: how the surface is provided, ordered by precedence.
* ``endpoint``:       connection metadata for clients (server roles only).
* ``tools``:          tool-surface toggles.
"""

from __future__ import annotations

MCP_DIRECTIONS = frozenset({"server", "client", "both"})
MCP_TRANSPORTS = frozenset({"streamable_http", "sse"})
MCP_EXPOSURES = frozenset({"internal", "public"})
MCP_AUTHS = frozenset(
    {"oidc", "app_password", "bearer_token", "upstream_session", "none"}
)
MCP_AUTH_SUBJECTS = frozenset({"user", "service_account", "administrator", "none"})
MCP_IMPLEMENTATIONS = frozenset({"native", "plugin", "sidecar", "external"})

MCP_KEYS = frozenset(
    {
        "enabled",
        "shared",
        "bond",
        "direction",
        "transport",
        "exposure",
        "auth",
        "auth_subject",
        "implementation",
        "endpoint",
        "tools",
    }
)
MCP_ENDPOINT_KEYS = frozenset({"service_key", "path", "port_key", "health_path"})
MCP_TOOLS_KEYS = frozenset({"read_only_default", "mutating_tools_enabled"})

MCP_SERVER_DIRECTIONS = frozenset({"server", "both"})
MCP_REQUIRED_ENDPOINT_KEYS = frozenset({"service_key", "path", "port_key"})
MCP_PRIVILEGED_AUTH_SUBJECTS = frozenset({"service_account", "administrator"})

DEFAULT_MCP_TRANSPORT = "streamable_http"


def value_is_templated(value: object) -> bool:
    return isinstance(value, str) and "{{" in value
