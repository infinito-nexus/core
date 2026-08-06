"""Vocabulary of the ``services.mcp`` block in ``meta/services.yml``.

Every role with an ``application_id`` declares exactly one ``mcp:`` entry.
The block is an audit disposition first and a deployable surface second:
``classification`` states what the role is, and only a deployable
classification may also carry ``enabled``/``shared`` and a served contract.

Field vocabulary (see ``docs/contributing/design/role/services/mcp.md``):

* ``classification``:  what this role is in the MCP audit. Required.
* ``reason``:          why a non-deployable classification cannot serve.
* ``direction``:       whether the role exposes MCP, consumes it, or both.
* ``transport``:       wire protocol of the endpoint.
* ``exposure``:        who may reach the endpoint.
* ``auth``:            authentication scheme guarding the endpoint.
* ``auth_subject``:    identity MCP calls execute as. ``user`` and ``oidc``
  additionally require a ``delegation`` block, because a rendered deployment
  bearer is a service account no matter what the metadata claims.
* ``delegation``:      recorded proof, at one exact upstream version, that
  per-user token acquisition, refresh, audience binding and revocation exist.
* ``implementation``:  how the surface is provided, ordered by precedence.
* ``credential``:      which principal the provider authenticates as, and
  where its secret is read from. Replaces the administrator token path.
* ``allowed_consumers``: client ``application_id`` values this provider
  admits. Discovery intersects it with the client's declared capabilities.
* ``supported_transports`` / ``supported_auths``: what a client can present.
* ``endpoint``:        connection metadata for clients (server roles only).
  ``key_credential`` names a credential of the same role whose value belongs in
  the URL path, and ``suffix`` the segment that follows it, for servers that
  address a session through the path rather than a header.
* ``adapter``:         immutable source contract of a repository-owned adapter.
* ``limits``:          the request, response, timeout, concurrency, pagination
  and stream ceilings the surface enforces.
* ``tools``:           exact tool allowlist, schema hash and mutation policy.
* ``source_url``:      upstream documentation or source of the MCP surface.
* ``supported_version``: the exact upstream version the contract was read at.
* ``minimum_version``: first upstream release shipping the surface.
"""

from __future__ import annotations

MCP_DIRECTIONS = frozenset({"server", "client", "both"})
MCP_TRANSPORTS = frozenset({"streamable_http", "sse"})
MCP_EXPOSURES = frozenset({"internal", "public"})
MCP_AUTHS = frozenset(
    {"oidc", "app_password", "basic_auth", "bearer_token", "upstream_session", "none"}
)
MCP_AUTH_SUBJECTS = frozenset({"user", "service_account", "administrator", "none"})
MCP_IMPLEMENTATIONS = frozenset({"native", "plugin", "sidecar", "adapter", "external"})

MCP_CLASSIFICATIONS = frozenset(
    {
        "native_server",
        "native_client",
        "native_both",
        "plugin_server",
        "sidecar_server",
        "adapter_server",
        "adapter_candidate",
        "blocked",
        "enabler",
        "subordinate",
        "no_surface",
    }
)

MCP_DEPLOYABLE_CLASSIFICATIONS = frozenset(
    {
        "native_server",
        "native_client",
        "native_both",
        "plugin_server",
        "sidecar_server",
        "adapter_server",
    }
)

MCP_AUDIT_ONLY_CLASSIFICATIONS = MCP_CLASSIFICATIONS - MCP_DEPLOYABLE_CLASSIFICATIONS

MCP_CLIENT_CLASSIFICATIONS = frozenset({"native_client", "native_both"})

MCP_REASONS = frozenset(
    {
        "no_remote_surface",
        "host_execution_boundary",
        "privileged_control_plane",
        "shared_engine_isolation",
        "administrative_surface",
        "duplicate_owner",
        "version_unverified",
        "licence",
        "hosted_only",
        "stdio_only",
        "interactive_browser_session",
        "unreviewed_third_party",
        "missing_dependency",
    }
)

MCP_ADAPTER_TYPES = frozenset(
    {
        "openapi_allowlist",
        "graphql_allowlist",
        "named_query",
        "s3_prefix",
        "prometheus_readonly",
        "n8n_workflow",
        "resource_readonly",
    }
)

MCP_SCOPED_ADAPTER_TYPES = frozenset(
    {"graphql_allowlist", "named_query", "s3_prefix", "resource_readonly"}
)

MCP_SPECIFICATION_ADAPTER_TYPES = frozenset({"openapi_allowlist", "graphql_allowlist"})

MCP_CREDENTIAL_SOURCES = frozenset({"token_store", "credentials"})

MCP_SERVED_KEYS = frozenset(
    {
        "direction",
        "transport",
        "exposure",
        "auth",
        "auth_subject",
        "delegation",
        "credential",
        "allowed_consumers",
        "supported_transports",
        "supported_auths",
        "endpoint",
        "adapter",
        "limits",
        "tools",
    }
)

MCP_KEYS = frozenset(
    {
        "enabled",
        "shared",
        "bond",
        "classification",
        "reason",
        "direction",
        "transport",
        "exposure",
        "auth",
        "auth_subject",
        "delegation",
        "implementation",
        "credential",
        "allowed_consumers",
        "supported_transports",
        "supported_auths",
        "endpoint",
        "adapter",
        "limits",
        "tools",
        "source_url",
        "supported_version",
        "minimum_version",
    }
)

MCP_PROVENANCE_KEYS = ("source_url", "supported_version", "minimum_version")

MCP_ENDPOINT_KEYS = frozenset(
    {
        "service_key",
        "path",
        "port_key",
        "key_credential",
        "suffix",
    }
)

MCP_CREDENTIAL_KEYS = frozenset({"owner", "source", "key"})

MCP_DELEGATION_KEYS = frozenset(
    {
        "verified_version",
        "source_url",
        "refresh",
        "revocation",
        "audience_binding",
    }
)

MCP_DELEGATION_PROOF_KEYS = frozenset({"refresh", "revocation", "audience_binding"})

MCP_ADAPTER_KEYS = frozenset(
    {
        "type",
        "image",
        "version",
        "digest",
        "upstream_api_version",
        "specification_path",
        "specification_sha256",
        "scope",
    }
)

MCP_ADAPTER_REQUIRED_KEYS = frozenset({"type", "image", "version", "digest"})

MCP_LIMITS_KEYS = frozenset(
    {
        "request_bytes",
        "response_bytes",
        "timeout_seconds",
        "concurrent_requests",
        "page_size",
        "result_items",
        "stream_seconds",
    }
)

MCP_TOOLS_KEYS = frozenset(
    {"allowlist", "schema_sha256", "read_only_default", "mutating_tools_enabled"}
)

MCP_TOOLS_BOOLEAN_KEYS = frozenset({"read_only_default", "mutating_tools_enabled"})

MCP_SERVER_DIRECTIONS = frozenset({"server", "both"})
MCP_CLIENT_DIRECTIONS = frozenset({"client", "both"})
MCP_REQUIRED_ENDPOINT_KEYS = frozenset({"service_key", "path", "port_key"})
MCP_PRIVILEGED_AUTH_SUBJECTS = frozenset({"service_account", "administrator"})
MCP_DELEGATED_AUTH_SUBJECTS = frozenset({"user"})
MCP_DELEGATED_AUTHS = frozenset({"oidc"})

MCP_FORBIDDEN_SURFACE_MARKERS = (
    "docker.sock",
    "/var/run/",
    "unix:",
    "file://",
    "sh -c",
    "bash -c",
    "${",
    "*",
)

MCP_SHA256_PREFIX = "sha256:"

DEFAULT_MCP_TRANSPORT = "streamable_http"


def value_is_templated(value: object) -> bool:
    return isinstance(value, str) and "{{" in value


def is_deployable(mcp: object) -> bool:
    """Return whether this block may carry a served surface and be discovered.

    Args:
        mcp: the role's ``services.mcp`` mapping, or anything else.
    """
    if not isinstance(mcp, dict):
        return False
    return mcp.get("classification") in MCP_DEPLOYABLE_CLASSIFICATIONS


def declares_delegation(mcp: object) -> bool:
    """Return whether this block claims to act as the requesting end user.

    Args:
        mcp: the role's ``services.mcp`` mapping, or anything else.
    """
    if not isinstance(mcp, dict):
        return False
    return (
        mcp.get("auth_subject") in MCP_DELEGATED_AUTH_SUBJECTS
        or mcp.get("auth") in MCP_DELEGATED_AUTHS
    )


def delegation_is_proven(mcp: object) -> bool:
    """Return whether a recorded per-version audit backs the delegation claim.

    Args:
        mcp: the role's ``services.mcp`` mapping, or anything else.
    """
    if not isinstance(mcp, dict):
        return False
    delegation = mcp.get("delegation")
    if not isinstance(delegation, dict):
        return False
    if not str(delegation.get("verified_version") or "").strip():
        return False
    if not str(delegation.get("source_url") or "").strip():
        return False
    return all(delegation.get(key) is True for key in MCP_DELEGATION_PROOF_KEYS)
