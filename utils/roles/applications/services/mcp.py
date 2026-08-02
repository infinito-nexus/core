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
  ``key_credential`` names a credential of the same role whose value belongs in
  the URL path, and ``suffix`` the segment that follows it, for servers that
  address a session through the path rather than a header.
* ``tools``:          tool-surface toggles.
* ``source_url``:     upstream documentation of the MCP surface.
* ``minimum_version``: first upstream release shipping it.
* ``notes``:          upstream caveats a deployment must respect.
* ``blocker``:        why an upstream surface stays unreachable here. Set it
  instead of ``direction``/``endpoint`` when the role documents a surface it
  cannot serve, so the audit does not report the absence as ``none``.
"""

from __future__ import annotations

MCP_DIRECTIONS = frozenset({"server", "client", "both"})
MCP_TRANSPORTS = frozenset({"streamable_http", "sse"})
MCP_EXPOSURES = frozenset({"internal", "public"})
MCP_AUTHS = frozenset(
    {"oidc", "app_password", "basic_auth", "bearer_token", "upstream_session", "none"}
)
MCP_AUTH_SUBJECTS = frozenset({"user", "service_account", "administrator", "none"})
MCP_IMPLEMENTATIONS = frozenset({"native", "plugin", "sidecar", "external"})

MCP_BLOCKERS = {"hosted_only": "external-only", "licence": "licence-gated"}

MCP_SERVED_KEYS = frozenset(
    {"direction", "transport", "exposure", "auth", "auth_subject", "endpoint", "tools"}
)

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
        "source_url",
        "minimum_version",
        "notes",
        "blocker",
    }
)

MCP_PROVENANCE_KEYS = ("source_url", "minimum_version", "notes")
MCP_ENDPOINT_KEYS = frozenset(
    {
        "service_key",
        "path",
        "port_key",
        "health_path",
        "key_credential",
        "suffix",
    }
)
MCP_TOOLS_KEYS = frozenset({"read_only_default", "mutating_tools_enabled"})

MCP_SERVER_DIRECTIONS = frozenset({"server", "both"})
MCP_REQUIRED_ENDPOINT_KEYS = frozenset({"service_key", "path", "port_key"})
MCP_PRIVILEGED_AUTH_SUBJECTS = frozenset({"service_account", "administrator"})

DEFAULT_MCP_TRANSPORT = "streamable_http"


def value_is_templated(value: object) -> bool:
    return isinstance(value, str) and "{{" in value
