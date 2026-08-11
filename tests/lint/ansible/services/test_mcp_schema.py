"""Schema lint for the ``mcp`` block.

A role declares ``mcp`` only when it actually serves or consumes MCP. Why a
role cannot is recorded once in the design documentation, not in a metadata
block per role restating an enum. What is declared here has to be complete,
with vocabulary from ``utils/roles/applications/mcp.py``.

It is a hard lint. It rejects:

* a block without a ``classification``, or with a non-deployable one: a role
  that cannot serve declares nothing,

* an unknown key inside ``mcp``, ``endpoint``, ``credential``, ``delegation``,
  ``adapter``, ``limits`` or ``tools``,
* a templated value on any MCP-specific field (only ``enabled``/``shared``
  may carry Jinja),
* an invalid ``direction`` / ``transport`` / ``exposure`` / ``auth`` /
  ``auth_subject`` / ``implementation``,
* a ``direction`` that contradicts the ``classification``,
* a server-capable block missing ``auth``, ``credential``,
  ``allowed_consumers`` or a complete ``endpoint``,
* a credential owned by ``administrator``, or read from an unknown source,
* ``auth: none`` combined with an ``exposure`` other than ``internal``,
* ``auth_subject: service_account|administrator`` combined with
  ``tools.mutating_tools_enabled: true``,
* ``auth_subject: user`` or ``auth: oidc`` without a ``delegation`` block
  recording refresh, revocation and audience binding at one exact version,
  because a rendered deployment bearer is a service account whatever the
  metadata claims,
* a client-capable block missing ``supported_transports`` /
  ``supported_auths``, or declaring an ``endpoint`` it does not serve,
* an ``endpoint.service_key`` that names no service in the same file, or an
  ``endpoint.port_key`` that resolves under neither ``ports.local`` nor
  ``ports.internal`` of the referenced service,
* an adapter or public surface without a complete ``limits`` block,
* ``implementation: adapter`` without a pinned, hash-checked adapter contract
  and an exact tool allowlist,
* a generic URL, runtime specification, free-form query, raw SQL, filesystem
  root, shell command, container socket or unrestricted bucket in an adapter.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-schema`` in the head of a ``meta/services.yml`` file
  exempts the whole file.
* ``# nocheck: mcp-schema`` on (or directly above) the offending line
  exempts that single finding.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping, Sequence
from functools import partial

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mcp import (
    MCP_ADAPTER_KEYS,
    MCP_ADAPTER_REQUIRED_KEYS,
    MCP_ADAPTER_TYPES,
    MCP_AUTH_SUBJECTS,
    MCP_AUTHS,
    MCP_CLASSIFICATIONS,
    MCP_CLIENT_DIRECTIONS,
    MCP_CREDENTIAL_KEYS,
    MCP_CREDENTIAL_SOURCES,
    MCP_DELEGATION_KEYS,
    MCP_DEPLOYABLE_CLASSIFICATIONS,
    MCP_DIRECTIONS,
    MCP_ENDPOINT_KEYS,
    MCP_EXPOSURES,
    MCP_FORBIDDEN_SURFACE_MARKERS,
    MCP_IMPLEMENTATIONS,
    MCP_KEYS,
    MCP_LIMITS_KEYS,
    MCP_PRIVILEGED_AUTH_SUBJECTS,
    MCP_REQUIRED_ENDPOINT_KEYS,
    MCP_SCOPED_ADAPTER_TYPES,
    MCP_SERVER_DIRECTIONS,
    MCP_SHA256_PREFIX,
    MCP_SPECIFICATION_ADAPTER_TYPES,
    MCP_TOOLS_BOOLEAN_KEYS,
    MCP_TOOLS_KEYS,
    MCP_TRANSPORTS,
    MCP_UPSTREAM_MCP_ADAPTER_TYPES,
    declares_delegation,
    delegation_is_proven,
    value_is_templated,
)
from utils.roles.mapping import ROLE_FILE_META_MCP, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "mcp-schema"

_ENUMS: tuple[tuple[str, frozenset[str]], ...] = (
    ("classification", MCP_CLASSIFICATIONS),
    ("direction", MCP_DIRECTIONS),
    ("transport", MCP_TRANSPORTS),
    ("exposure", MCP_EXPOSURES),
    ("auth", MCP_AUTHS),
    ("auth_subject", MCP_AUTH_SUBJECTS),
    ("implementation", MCP_IMPLEMENTATIONS),
)

_CLASSIFICATION_DIRECTIONS: dict[str, frozenset[str]] = {
    "native_server": MCP_SERVER_DIRECTIONS,
    "plugin_server": MCP_SERVER_DIRECTIONS,
    "sidecar_server": MCP_SERVER_DIRECTIONS,
    "adapter_server": MCP_SERVER_DIRECTIONS,
    "native_client": MCP_CLIENT_DIRECTIONS,
    "native_both": frozenset({"both"}),
}

_FORBIDDEN_OWNER = "administrator"


def _flag(
    errors: list[str], lines: list[str], rel: str, key: str, message: str
) -> None:
    line_no = _locate_line(lines, key)
    if line_no is not None and is_suppressed_at(lines, line_no, _RULE):
        return
    errors.append(f"{message} ({rel})")


def _locate_line(lines: list[str], key: str) -> int | None:
    """Return the 1-based line declaring ``key``, or None.

    Args:
        lines: the role's ``meta/mcp.yml`` split into lines.
        key: the schema key a finding is reported against.

    The whole file is the block, so there is no enclosing ``mcp:`` line to
    anchor on. Anchoring on one made every lookup miss, which silently
    disabled per-line suppression everywhere.
    """
    needle = f"{key}:"
    for idx, raw in enumerate(lines, start=1):
        if raw.strip().startswith(needle):
            return idx
    return None


def _strings(value: object) -> list[str]:
    """Return every string reachable inside a nested mapping or sequence.

    Args:
        value: any metadata value; scalars, mappings and sequences are walked.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, Sequence):
        return [s for v in value for s in _strings(v)]
    return []


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_exact_names(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(v, str) and v.strip() and "*" not in v for v in value)
    )


class TestMcpSchema(unittest.TestCase):
    """Hard lint: every deployable ``mcp`` block obeys the contract."""

    def test_mcp_schema(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        errors: list[str] = []

        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            mcp_path = role_dir / ROLE_FILE_META_MCP
            if not mcp_path.is_file():
                continue
            rel = mcp_path.relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(str(mcp_path)).splitlines()

            if is_suppressed_in_head(lines, _RULE):
                continue

            try:
                mcp = load_yaml_any(str(mcp_path), default_if_missing={})
            except Exception:
                continue

            services = load_yaml_any(
                str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
            )
            if not isinstance(services, Mapping):
                services = {}
            if mcp is None:
                continue

            prefix = f"{role_dir.name}: mcp"
            flag = partial(_flag, errors, lines, rel)

            if not isinstance(mcp, Mapping):
                errors.append(f"{prefix} MUST be a mapping. ({rel})")
                continue

            unknown = set(mcp) - MCP_KEYS
            if unknown:
                flag(min(unknown), f"{prefix} has unknown key(s) {sorted(unknown)}")

            for key, allowed in _ENUMS:
                if key not in mcp:
                    continue
                value = mcp.get(key)
                if value_is_templated(value):
                    flag(key, f"{prefix}.{key} MUST be a literal, not Jinja")
                elif value not in allowed:
                    flag(
                        key,
                        f"{prefix}.{key} has invalid value {value!r}; "
                        f"allowed: {sorted(allowed)}",
                    )

            classification = mcp.get("classification")
            if classification not in MCP_DEPLOYABLE_CLASSIFICATIONS:
                flag(
                    "classification",
                    f"{prefix}.classification {classification!r} is not "
                    f"deployable; a role that cannot serve or consume MCP "
                    f"declares no mcp block at all. Allowed: "
                    f"{sorted(MCP_DEPLOYABLE_CLASSIFICATIONS)}",
                )
                continue

            self._check_deployable(
                mcp, services, prefix, flag, role_dir.name, classification
            )

        if errors:
            self.fail(
                f"mcp schema violations ({len(errors)}):\n" + "\n".join(sorted(errors))
            )

    def _check_deployable(
        self, mcp, services, prefix, flag, role, classification
    ) -> None:
        direction = mcp.get("direction")
        if "direction" not in mcp:
            flag("direction", f"{prefix} is missing required 'direction'")

        expected = _CLASSIFICATION_DIRECTIONS.get(str(classification))
        if expected and direction not in expected:
            flag(
                "direction",
                f"{prefix}.direction {direction!r} contradicts classification "
                f"{classification!r}; allowed: {sorted(expected)}",
            )

        server_capable = direction in MCP_SERVER_DIRECTIONS
        client_capable = direction in MCP_CLIENT_DIRECTIONS

        self._check_no_peer_gate(mcp, prefix, flag)
        self._check_delegation(mcp, prefix, flag)
        self._check_tools(mcp, prefix, flag)

        if client_capable:
            self._check_client(mcp, prefix, flag, server_capable)
        if server_capable:
            self._check_credential(mcp, prefix, flag)
            self._check_consumers(mcp, prefix, flag)
            self._check_endpoint(mcp, services, prefix, flag)
            if "auth" not in mcp:
                flag("auth", f"{prefix} server-capable block is missing 'auth'")
            if "transport" not in mcp:
                flag(
                    "transport",
                    f"{prefix} server-capable block is missing 'transport'; the "
                    f"deploy-time probe reads it strictly and a consumer cannot "
                    f"pick a client without it",
                )

        if mcp.get("auth") == "none" and mcp.get("exposure") != "internal":
            flag("auth", f"{prefix} 'auth: none' requires 'exposure: internal'")

        is_adapter = mcp.get("implementation") == "adapter"
        if is_adapter != (classification == "adapter_server"):
            flag(
                "implementation",
                f"{prefix} classification {classification!r} and implementation "
                f"{mcp.get('implementation')!r} disagree about being an adapter",
            )

        if is_adapter or mcp.get("exposure") == "public":
            self._check_limits(mcp, prefix, flag)
        if is_adapter:
            self._check_adapter(mcp, prefix, flag, role)

    def _check_no_peer_gate(self, mcp, prefix, flag) -> None:
        """Pairing is the allowed_consumers intersection, never a deployed peer.

        A block that reads ``'web-app-openwebui' in group_names`` turns "that
        client happens to be deployed" into "that client may connect", which is
        a different question and one nobody declared. It also cannot scale: each
        new client would need an edit in every provider.
        """
        for key in ("enabled", "shared"):
            value = mcp.get(key)
            if isinstance(value, str) and "group_names" in value:
                flag(
                    key,
                    f"{prefix}.{key} gates on group_names; provider enablement "
                    f"is operator or variant state, and pairing is the "
                    f"allowed_consumers intersection",
                )

    def _check_delegation(self, mcp, prefix, flag) -> None:
        delegation = mcp.get("delegation")
        if delegation is not None:
            if not isinstance(delegation, Mapping):
                flag("delegation", f"{prefix}.delegation MUST be a mapping")
                return
            unknown = set(delegation) - MCP_DELEGATION_KEYS
            if unknown:
                flag(
                    "delegation",
                    f"{prefix}.delegation has unknown key(s) {sorted(unknown)}",
                )
        if not declares_delegation(mcp):
            if delegation is not None:
                flag(
                    "delegation",
                    f"{prefix} declares 'delegation' without claiming user "
                    f"delegation; drop it or set auth_subject: user",
                )
            return
        if not delegation_is_proven(mcp):
            flag(
                "auth_subject",
                f"{prefix} claims user delegation but records no proof. A "
                f"rendered deployment bearer is a service account: either add a "
                f"'delegation' block with verified_version, source_url and "
                f"refresh/revocation/audience_binding all true, or declare "
                f"auth_subject: service_account",
            )

    def _check_client(self, mcp, prefix, flag, server_capable) -> None:
        transports = mcp.get("supported_transports")
        if not _is_exact_names(transports):
            flag(
                "supported_transports",
                f"{prefix} client-capable block needs a non-empty "
                f"'supported_transports' list",
            )
        elif set(transports) - MCP_TRANSPORTS:
            flag(
                "supported_transports",
                f"{prefix}.supported_transports has invalid value(s) "
                f"{sorted(set(transports) - MCP_TRANSPORTS)}",
            )

        auths = mcp.get("supported_auths")
        if not _is_exact_names(auths):
            flag(
                "supported_auths",
                f"{prefix} client-capable block needs a non-empty "
                f"'supported_auths' list",
            )
        elif set(auths) - MCP_AUTHS:
            flag(
                "supported_auths",
                f"{prefix}.supported_auths has invalid value(s) "
                f"{sorted(set(auths) - MCP_AUTHS)}",
            )

        if not server_capable and "endpoint" in mcp:
            flag(
                "endpoint",
                f"{prefix} is a client, so it MUST NOT declare an 'endpoint'",
            )

    def _check_credential(self, mcp, prefix, flag) -> None:
        credential = mcp.get("credential")
        if not isinstance(credential, Mapping):
            flag(
                "credential",
                f"{prefix} server-capable block is missing 'credential'; the "
                f"provider identity MUST be declared, not inherited from the "
                f"administrator",
            )
            return
        unknown = set(credential) - MCP_CREDENTIAL_KEYS
        if unknown:
            flag(
                "credential",
                f"{prefix}.credential has unknown key(s) {sorted(unknown)}",
            )
        missing = MCP_CREDENTIAL_KEYS - set(credential)
        if missing:
            flag(
                "credential",
                f"{prefix}.credential is missing key(s) {sorted(missing)}",
            )
        owner = str(credential.get("owner") or "").strip()
        if owner == _FORBIDDEN_OWNER:
            flag(
                "owner",
                f"{prefix}.credential.owner MUST NOT be {_FORBIDDEN_OWNER!r}; "
                f"declare a dedicated non-login identity for this provider",
            )
        source = credential.get("source")
        if source is not None and source not in MCP_CREDENTIAL_SOURCES:
            flag(
                "source",
                f"{prefix}.credential.source {source!r} is invalid; allowed: "
                f"{sorted(MCP_CREDENTIAL_SOURCES)}",
            )

    def _check_consumers(self, mcp, prefix, flag) -> None:
        consumers = mcp.get("allowed_consumers")
        if not _is_exact_names(consumers):
            flag(
                "allowed_consumers",
                f"{prefix} server-capable block needs a non-empty "
                f"'allowed_consumers' list of client application ids",
            )

    def _check_endpoint(self, mcp, services, prefix, flag) -> None:
        endpoint = mcp.get("endpoint")
        if not isinstance(endpoint, Mapping):
            flag("endpoint", f"{prefix} server-capable block is missing 'endpoint'")
            return
        missing = MCP_REQUIRED_ENDPOINT_KEYS - set(endpoint)
        if missing:
            flag("endpoint", f"{prefix}.endpoint is missing key(s) {sorted(missing)}")
        unknown = set(endpoint) - MCP_ENDPOINT_KEYS
        if unknown:
            flag("endpoint", f"{prefix}.endpoint has unknown key(s) {sorted(unknown)}")

        service_key = endpoint.get("service_key")
        if service_key is None:
            return
        target = services.get(str(service_key))
        if not isinstance(target, Mapping):
            flag(
                "service_key",
                f"{prefix}.endpoint.service_key {service_key!r} names no service "
                f"in this file",
            )
            return
        ports = target.get("ports")
        ports = ports if isinstance(ports, Mapping) else {}
        port_key = endpoint.get("port_key")
        if port_key is not None and not any(
            isinstance(ports.get(ns), Mapping) and port_key in ports[ns]
            for ns in ("local", "internal")
        ):
            flag(
                "port_key",
                f"{prefix}.endpoint.port_key {port_key!r} resolves under neither "
                f"ports.local nor ports.internal of service {service_key!r}",
            )

    def _check_limits(self, mcp, prefix, flag) -> None:
        limits = mcp.get("limits")
        if not isinstance(limits, Mapping):
            flag(
                "limits",
                f"{prefix} needs an explicit 'limits' block; an adapter or "
                f"public surface without ceilings is unbounded",
            )
            return
        unknown = set(limits) - MCP_LIMITS_KEYS
        if unknown:
            flag("limits", f"{prefix}.limits has unknown key(s) {sorted(unknown)}")
        missing = MCP_LIMITS_KEYS - set(limits)
        if missing:
            flag("limits", f"{prefix}.limits is missing key(s) {sorted(missing)}")
        for key in MCP_LIMITS_KEYS & set(limits):
            if not _is_positive_int(limits.get(key)):
                flag(key, f"{prefix}.limits.{key} MUST be a positive integer")

    def _check_tools(self, mcp, prefix, flag) -> None:
        tools = mcp.get("tools")
        if "tools" in mcp and not isinstance(tools, Mapping):
            flag("tools", f"{prefix}.tools MUST be a mapping")
        tools = tools if isinstance(tools, Mapping) else {}
        unknown = set(tools) - MCP_TOOLS_KEYS
        if unknown:
            flag("tools", f"{prefix}.tools has unknown key(s) {sorted(unknown)}")
        self._check_writer_allowlist(tools, prefix, flag)
        self._check_upstream_serves(mcp, tools, prefix, flag)

        for key in MCP_TOOLS_BOOLEAN_KEYS & set(tools):
            if not isinstance(tools.get(key), bool):
                flag(key, f"{prefix}.tools.{key} MUST be a boolean")
        privileged = mcp.get("auth_subject") in MCP_PRIVILEGED_AUTH_SUBJECTS
        mutating = tools.get("mutating_tools_enabled")
        enforced = mcp.get("implementation") == "adapter"
        if privileged and mutating is not False and not enforced:
            flag(
                "auth_subject",
                f"{prefix} '{mcp.get('auth_subject')}' subject may only enable "
                f"mutating tools behind a gateway that enforces the allowlist on "
                f"tools/call; without one the flag records an intention that "
                f"nothing upholds, so it MUST be false",
            )
        if (
            privileged
            and mutating is True
            and enforced
            and not tools.get("writer_allowlist")
        ):
            flag(
                "writer_allowlist",
                f"{prefix} enables mutating tools but names no "
                f"tools.writer_allowlist, so every reader would reach the writes "
                f"too; the point of the split is that they get different bearers",
            )

    def _check_writer_allowlist(self, tools, prefix, flag) -> None:
        allowlist = tools.get("allowlist")
        if not isinstance(allowlist, list):
            return
        writer = tools.get("writer_allowlist")
        if writer is None:
            return
        if not _is_exact_names(writer):
            flag(
                "writer_allowlist",
                f"{prefix}.tools.writer_allowlist MUST name exact tools",
            )
            return
        missing = sorted(set(allowlist) - set(writer))
        if missing:
            flag(
                "writer_allowlist",
                f"{prefix}.tools.writer_allowlist omits {missing}, which a reader "
                f"may already reach; a writer that loses a read tool is a "
                f"narrower grant wearing the wider name",
            )
        if set(writer) == set(allowlist):
            flag(
                "writer_allowlist",
                f"{prefix}.tools.writer_allowlist repeats the allowlist; omit it, "
                f"a provider with no extra write surface needs one contract, "
                f"not two",
            )
        serves = tools.get("upstream_serves")
        if isinstance(serves, list) and serves:
            undeclared = sorted(set(writer) - set(serves))
            if undeclared:
                flag(
                    "writer_allowlist",
                    f"{prefix}.tools.writer_allowlist names {undeclared} which "
                    f"the upstream does not serve",
                )

    def _check_upstream_serves(self, mcp, tools, prefix, flag) -> None:
        """``allowlist`` is what the platform permits; ``upstream_serves`` is what
        the upstream actually offers. State the second only where it DIFFERS,
        because a provider that serves exactly what is allowed would otherwise
        carry the same list twice and the copies would drift apart.

        The difference between the two measures unenforced exposure: where it is
        non-empty the allowlist is an intention rather than a constraint, and the
        provider needs a gateway in front of it.

        Three exemptions, all semantic: an adapter authors its tools here against
        a REST upstream, so there is nothing to observe; a provider declared
        ``enabled: false`` is never admitted; and ``upstream_serves: dynamic``
        covers an upstream that composes its surface at runtime, such as one
        proxying MCP servers an administrator configures, where no set of names
        could be pinned at author time."""
        if mcp.get("direction") not in MCP_SERVER_DIRECTIONS:
            return
        adapter = mcp.get("adapter")
        adapter_type = adapter.get("type") if isinstance(adapter, Mapping) else None
        if (
            mcp.get("implementation") == "adapter"
            and adapter_type not in MCP_UPSTREAM_MCP_ADAPTER_TYPES
        ):
            return
        if mcp.get("enabled") is False:
            return

        allowlist = tools.get("allowlist")
        serves = tools.get("upstream_serves")
        if serves == "dynamic":
            if not _is_exact_names(tools.get("categories")):
                flag(
                    "categories",
                    f"{prefix}.tools.categories MUST pin the categories the "
                    f"deployment permits: an upstream that composes its tools at "
                    f"runtime and switches only whole categories cannot honour a "
                    f"per-tool allowlist, so the category is the finest contract "
                    f"it can keep and 'dynamic' alone would permit everything",
                )
            return

        if not isinstance(allowlist, list) or not allowlist:
            flag(
                "allowlist",
                f"{prefix}.tools.allowlist MUST name the tools the platform "
                f"permits; an empty list reads as a pass while leaving every "
                f"tool the upstream serves reachable",
            )
            return

        if serves is None:
            return

        if not isinstance(serves, list) or not serves:
            flag(
                "upstream_serves",
                f"{prefix}.tools.upstream_serves MUST list every tool the "
                f"upstream offers at supported_version, or be omitted when it "
                f"is identical to the allowlist",
            )
            return

        undeclared = sorted(set(allowlist) - set(serves))
        if undeclared:
            flag(
                "allowlist",
                f"{prefix}.tools.allowlist names {undeclared} which the "
                f"upstream does not serve; the platform would advertise a "
                f"tool that cannot run",
            )
            return

        if sorted(serves) == sorted(allowlist):
            flag(
                "upstream_serves",
                f"{prefix}.tools.upstream_serves repeats the allowlist; omit it, "
                f"absence already means the upstream serves exactly what is "
                f"allowed",
            )

    def _check_adapter(self, mcp, prefix, flag, role) -> None:
        adapter = mcp.get("adapter")
        if not isinstance(adapter, Mapping):
            flag("adapter", f"{prefix} implementation: adapter is missing 'adapter'")
            return
        unknown = set(adapter) - MCP_ADAPTER_KEYS
        if unknown:
            flag("adapter", f"{prefix}.adapter has unknown key(s) {sorted(unknown)}")
        missing = MCP_ADAPTER_REQUIRED_KEYS - set(adapter)
        if missing:
            flag("adapter", f"{prefix}.adapter is missing key(s) {sorted(missing)}")

        adapter_type = adapter.get("type")
        if adapter_type not in MCP_ADAPTER_TYPES:
            flag(
                "type",
                f"{prefix}.adapter.type {adapter_type!r} is invalid; allowed: "
                f"{sorted(MCP_ADAPTER_TYPES)}",
            )

        digest = str(adapter.get("digest") or "")
        if not digest.startswith(MCP_SHA256_PREFIX):
            flag(
                "digest",
                f"{prefix}.adapter.digest MUST pin an immutable "
                f"{MCP_SHA256_PREFIX}… image digest",
            )
        elif set(digest[len(MCP_SHA256_PREFIX) :]) <= {"0"}:
            flag(
                "digest",
                f"{prefix}.adapter.digest is an all-zero placeholder, which "
                f"pins nothing; the build resolves this digest, so it must name "
                f"the real base image",
            )

        if adapter_type in MCP_UPSTREAM_MCP_ADAPTER_TYPES:
            spec = str(adapter.get("specification_path") or "")
            if not spec:
                flag(
                    "specification_path",
                    f"{prefix}.adapter.specification_path MUST name the tool "
                    f"contract the passthrough enforces; an MCP upstream exposes "
                    f"no method to infer a tool's blast radius from, so each tool "
                    f"has to declare whether it mutates",
                )

        if adapter_type in MCP_SPECIFICATION_ADAPTER_TYPES:
            spec = str(adapter.get("specification_path") or "")
            if not spec.startswith(f"roles/{role}/files/"):
                flag(
                    "specification_path",
                    f"{prefix}.adapter.specification_path MUST be a checked-in "
                    f"path under roles/{role}/files/, never a runtime document "
                    f"or remote URL",
                )
            elif not (PROJECT_ROOT / spec).is_file():
                flag(
                    "specification_path",
                    f"{prefix}.adapter.specification_path {spec!r} does not exist",
                )
            if not str(adapter.get("specification_sha256") or "").startswith(
                MCP_SHA256_PREFIX
            ):
                flag(
                    "specification_sha256",
                    f"{prefix}.adapter.specification_sha256 MUST pin the "
                    f"checked-in specification",
                )

        if adapter_type in MCP_SCOPED_ADAPTER_TYPES and not _is_exact_names(
            adapter.get("scope")
        ):
            flag(
                "scope",
                f"{prefix}.adapter.type {adapter_type!r} needs a non-empty "
                f"'scope' naming the exact buckets, prefixes, collections or "
                f"queries it may reach; an unrestricted scope is rejected",
            )

        for text in _strings(adapter):
            for marker in MCP_FORBIDDEN_SURFACE_MARKERS:
                if marker in text:
                    flag(
                        "adapter",
                        f"{prefix}.adapter contains {marker!r}, which opens a "
                        f"shell, socket, filesystem or unrestricted surface",
                    )

        tools = mcp.get("tools")
        tools = tools if isinstance(tools, Mapping) else {}
        if not _is_exact_names(tools.get("allowlist")):
            flag(
                "allowlist",
                f"{prefix}.tools.allowlist MUST name every exposed tool exactly; "
                f"an adapter never mirrors a whole upstream API",
            )
        if not str(tools.get("schema_sha256") or "").startswith(MCP_SHA256_PREFIX):
            flag(
                "schema_sha256",
                f"{prefix}.tools.schema_sha256 MUST pin the reviewed tool schema "
                f"so upstream drift fails closed",
            )


class TestMcpConsumerCompatibility(unittest.TestCase):
    """Hard lint: a provider only admits clients that can actually connect.

    ``mcp_servers`` aborts a run when a provider authorized a consumer whose
    transport or auth it cannot serve, because a client that silently ends up
    with fewer tools than declared looks exactly like one that works. Catching
    the same mismatch statically means a metadata edit fails here rather than
    an hour into a deploy.
    """

    def test_every_allowed_consumer_can_connect(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest("no roles/ directory")

        blocks: dict[str, Mapping] = {}
        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            mcp_path = role_dir / ROLE_FILE_META_MCP
            if not mcp_path.is_file():
                continue
            mcp = load_yaml_any(str(mcp_path), default_if_missing={})
            if isinstance(mcp, Mapping):
                blocks[role_dir.name] = mcp

        errors: list[str] = []
        for role, mcp in blocks.items():
            if mcp.get("direction") not in MCP_SERVER_DIRECTIONS:
                continue
            transport = mcp.get("transport")
            auth = mcp.get("auth")
            for consumer in mcp.get("allowed_consumers") or []:
                client = blocks.get(consumer)
                if client is None:
                    continue
                if transport not in (client.get("supported_transports") or []):
                    errors.append(
                        f"{role} admits {consumer}, but speaks {transport!r} "
                        f"and {consumer} speaks "
                        f"{client.get('supported_transports')}"
                    )
                if auth not in (client.get("supported_auths") or []):
                    errors.append(
                        f"{role} admits {consumer}, but authenticates with "
                        f"{auth!r} and {consumer} can present "
                        f"{client.get('supported_auths')}"
                    )

        if errors:
            self.fail(
                f"incompatible MCP provider/consumer pairs ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in sorted(errors))
            )


if __name__ == "__main__":
    unittest.main()
