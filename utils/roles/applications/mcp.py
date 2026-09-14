"""Vocabulary of the ``mcp`` block in ``meta/services.yml``.

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
Admission is not declared here. A client marks itself once, in its own
``meta/services.yml`` self-entry, as ``mcp_consumer: true``; a provider
deviates by carrying ``mcp_consumer: false`` on that client's entry in its
own ``meta/services.yml``. ``derive_allowed_consumers`` resolves the pair.

* ``supported_transports`` / ``supported_auths``: what a client can present.
* ``endpoint``:        connection metadata for clients (server roles only).
* ``adapter``:         immutable source contract of a repository-owned adapter.
  ``category_allowlist`` suits an upstream that switches whole categories and
  offers no per-tool filter, where a tool allowlist would be unenforceable;
  ``mcp_passthrough`` fronts an upstream that already speaks MCP instead of
  translating REST. ``upstream_path`` names that upstream where it lives on the
  application's own vhost, so the proxy can hide it: reaching it directly walks
  past the allowlist the adapter exists to enforce. A provider whose upstream is
  a separate sidecar declares ``upstream_network`` instead and has nothing to
  hide there.
* ``limits``:          the request, response, timeout, concurrency, pagination
  and stream ceilings the surface enforces.
* ``tools``:           ``allowlist`` is what a reader may reach and
  ``writer_allowlist`` what a writer may reach; the deployment renders one
  contract per role, each with its own bearer, because the gateway tells
  callers apart by credential and by nothing else. ``allowlist`` is policy,
  what the platform lets a consumer
  reach, and is only a constraint where a gateway enforces it. ``upstream_serves``
  is the observation: every tool the upstream offers at the deployed version.
  State it only where it DIFFERS from the allowlist; absence means the two are
  identical, which is the normal case for a provider that serves exactly what is
  allowed. The difference between them measures unenforced exposure, and a
  provider whose difference is non-empty needs a gateway in front. Plus schema
  hash and mutation policy.
* ``mutating_proofs``: required once ``tools.mutating_tools_enabled`` is true.
  Names the artifact proving each of confirmation, authorization, idempotency,
  audit and reversal for the mutating variant, separately from the read-only
  one.
* ``source_url``:      upstream documentation or source of the MCP surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.roles.entity.name import get_entity_name

if TYPE_CHECKING:
    from collections.abc import Mapping

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
        "category_allowlist",
        "mcp_passthrough",
    }
)

MCP_UPSTREAM_MCP_ADAPTER_TYPES = frozenset({"mcp_passthrough"})

MCP_SCOPED_ADAPTER_TYPES = frozenset(
    {"graphql_allowlist", "named_query", "s3_prefix", "resource_readonly"}
)

MCP_SPECIFICATION_ADAPTER_TYPES = frozenset({"openapi_allowlist", "graphql_allowlist"})

MCP_CREDENTIAL_SOURCES = frozenset({"token_store", "credentials"})
MCP_SOURCE_TOKEN_STORE = "token_store"  # noqa: S105 - a source name, not a secret
MCP_SOURCE_CREDENTIALS = "credentials"
MCP_FORBIDDEN_CREDENTIAL_OWNER = "administrator"

MCP_KEYS = frozenset(
    {
        "enabled",
        "shared",
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
        "supported_transports",
        "supported_auths",
        "endpoint",
        "adapter",
        "limits",
        "tools",
        "mutating_proofs",
        "source_url",
    }
)

MCP_ENDPOINT_KEYS = frozenset(
    {
        "service_key",
        "path",
        "port_key",
        "host_header",
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
        "upstream_api_version",
        "upstream_network",
        "specification_path",
        "specification_sha256",
        "scope",
        "upstream_transport",
        "upstream_path",
    }
)

MCP_ADAPTER_REQUIRED_KEYS = frozenset({"type"})

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
    {
        "allowlist",
        "mutating",
        "writer_allowlist",
        "upstream_serves",
        "categories",
        "schema_sha256",
        "read_only_default",
        "mutating_tools_enabled",
        "read_probe",
    }
)

MCP_READ_PROBE_KEYS = frozenset({"tool", "arguments"})

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


MCP_CONSUMER_FLAG = "mcp_consumer"


def value_is_templated(value: object) -> bool:
    return isinstance(value, str) and "{{" in value


def declares_mcp_consumer(role_id: str, services: object) -> bool:
    """Return whether a role marks itself an MCP client in its own services.

    Args:
        role_id: the role's ``application_id``.
        services: that role's ``services`` mapping, or anything else.
    """
    if not isinstance(services, dict):
        return False
    entry = services.get(get_entity_name(role_id))
    return isinstance(entry, dict) and entry.get(MCP_CONSUMER_FLAG) is True


def admits_mcp_consumer(provider_services: object, consumer_id: str) -> bool:
    """Return whether a provider admits one client.

    An omitted flag inherits the client's own declaration; only an explicit
    ``mcp_consumer: false`` excludes, so a deliberate exclusion is
    distinguishable from a forgotten entry.

    Args:
        provider_services: the provider's ``services`` mapping.
        consumer_id: the client's ``application_id``.
    """
    if not isinstance(provider_services, dict):
        return True
    entry = provider_services.get(get_entity_name(consumer_id))
    if isinstance(entry, dict) and MCP_CONSUMER_FLAG in entry:
        return entry[MCP_CONSUMER_FLAG] is True
    return True


def derive_allowed_consumers(
    provider_id: str, services_by_role: dict[str, object]
) -> list[str]:
    """Return the client application ids a provider admits, sorted.

    Args:
        provider_id: the provider's ``application_id``.
        services_by_role: every role's ``services`` mapping, keyed by role id.
    """
    provider_services = services_by_role.get(provider_id)
    return sorted(
        role_id
        for role_id, services in services_by_role.items()
        if role_id != provider_id
        and declares_mcp_consumer(role_id, services)
        and admits_mcp_consumer(provider_services, role_id)
    )


def derive_mcp_presence(applications: dict[str, Any]) -> dict[str, Any]:
    """Materialise every ``mcp`` topic's enable state from its declared peers.

    Args:
        applications: ``{application_id: config}``, mutated in place.

    Returns:
        The same mapping.

    A surface is reachable only while a peer that uses it is deployed, so both
    keys resolve to the ``in group_names`` form the rest of the tree uses, and
    to ``False`` when a role has no peer at all. An explicitly configured
    ``enabled``/``shared`` always wins, so config stays the override channel.
    Keying on peer PRESENCE rather than on a peer's own value is required: a
    re-entrant read under ``_RENDER_GUARD`` returns the unrendered dict.

    The resolved block replaces the mapping rather than being written into it.
    ``_build_role_base_config`` parks the YAML cache's own object under ``mcp``,
    so an in-place write would inject these keys into every later raw read of
    ``meta/mcp.yml``.
    """
    blocks = {
        role_id: config["mcp"]
        for role_id, config in applications.items()
        if isinstance(config, dict) and isinstance(config.get("mcp"), dict)
    }
    services_by_role = {
        role_id: (config or {}).get("services")
        for role_id, config in applications.items()
        if isinstance(config, dict)
    }
    for role_id, block in blocks.items():
        direction = str(block.get("direction") or "").lower()
        peers: set[str] = set()
        if direction in ("server", "both"):
            peers |= set(derive_allowed_consumers(role_id, services_by_role))
        if direction in ("client", "both") and declares_mcp_consumer(
            role_id, services_by_role.get(role_id)
        ):
            peers |= {
                peer
                for peer, peer_block in blocks.items()
                if peer != role_id
                and str(peer_block.get("direction") or "").lower() in ("server", "both")
                and admits_mcp_consumer(services_by_role.get(peer), role_id)
            }
        value: Any = (
            "{{ " + " or ".join(f"'{p}' in group_names" for p in sorted(peers)) + " }}"
            if peers
            else False
        )
        resolved = dict(block)
        resolved.setdefault("enabled", value)
        resolved.setdefault("shared", value)
        applications[role_id]["mcp"] = resolved
    return applications


def is_deployable(mcp: object) -> bool:
    """Return whether this block may carry a served surface and be discovered.

    Args:
        mcp: the role's ``mcp`` mapping, or anything else.
    """
    if not isinstance(mcp, dict):
        return False
    return mcp.get("classification") in MCP_DEPLOYABLE_CLASSIFICATIONS


def declares_delegation(mcp: object) -> bool:
    """Return whether this block claims to act as the requesting end user.

    Args:
        mcp: the role's ``mcp`` mapping, or anything else.
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
        mcp: the role's ``mcp`` mapping, or anything else.
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


def resolve_credential(
    server: Mapping[str, Any],
    users: Mapping[str, Any],
    role_credentials: Mapping[str, Any],
) -> tuple[str, str]:
    """Return the provider's declared secret and the owner it belongs to.

    Args:
        server: a discovered ``direction=server`` entry.
        users: the merged users mapping, carrying each principal's tokens.
        role_credentials: the provider role's own ``secrets.credentials``
            mapping, which is where every other consumer addresses them.

    Returns an empty token when the declaration is incomplete or the principal
    holds nothing; the caller turns that into ``credential_missing``.
    """
    credential = server.get("credential") or {}
    owner = str(credential.get("owner") or "").strip()
    source = str(credential.get("source") or "").strip()
    key = str(credential.get("key") or "").strip()
    if not owner or not source or not key or owner == MCP_FORBIDDEN_CREDENTIAL_OWNER:
        return "", owner

    if source == MCP_SOURCE_TOKEN_STORE:
        principal = users.get(owner)
        tokens = principal.get("tokens") if isinstance(principal, dict) else None
        value = (tokens or {}).get(key) if isinstance(tokens, dict) else None
        return str(value or "").strip(), owner

    if source == MCP_SOURCE_CREDENTIALS:
        return str(role_credentials.get(key) or "").strip(), owner

    return "", owner
