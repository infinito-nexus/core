"""Policy layer for fronting an upstream that already speaks MCP.

The REST layer in :mod:`policy` derives a tool's blast radius from its HTTP
method: anything outside GET/HEAD mutates. An upstream MCP server exposes no
method, only a name, so that inference is unavailable and every tool must
declare whether it mutates. A tool that does not say is rejected at startup
rather than assumed harmless.

Fronting such an upstream is what gives a plugin- or native-implemented
provider an enforcement point at all. Without it the declared allowlist is a
statement about the upstream rather than a constraint on it, and a client can
reach any operation the upstream happens to serve by naming it.

This module decides; it performs no I/O, so the rules stay testable without a
live upstream.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import policy

if TYPE_CHECKING:
    from collections.abc import Mapping

KIND_MCP = "mcp"
KIND_REST = "rest"
KINDS = frozenset({KIND_MCP, KIND_REST})


def contract_kind(contract: Mapping[str, Any]) -> str:
    """Return the upstream kind a contract declares.

    Args:
        contract: the loaded contract.

    The kind is required. Inferring it from the presence of other keys would
    make a malformed contract look like a valid one of the other kind.
    """
    kind = str(contract.get("upstream_kind") or "").strip()
    if kind not in KINDS:
        raise policy.ContractError(
            f"contract must declare upstream_kind as one of {sorted(KINDS)}; "
            f"got {kind!r}"
        )
    return kind


def declares_mcp_upstream(raw: str) -> bool:
    """Whether a rendered contract asks for the MCP passthrough.

    Args:
        raw: the ``ADAPTER_CONTRACT`` JSON document.

    Routing question, deliberately total: a contract that omits the key is a
    REST one, which is what every adapter rendered before this transport
    existed. Validation of an MCP contract stays strict in
    :func:`load_mcp_contract`.
    """
    try:
        contract = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return False
    return (
        isinstance(contract, dict)
        and str(contract.get("upstream_kind") or "").strip() == KIND_MCP
    )


def load_mcp_contract(raw: str) -> dict[str, Any]:
    """Return the validated contract for an MCP-speaking upstream.

    Args:
        raw: the ``ADAPTER_CONTRACT`` JSON document.
    """
    try:
        contract = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise policy.ContractError(f"contract is not JSON: {error}") from error
    if not isinstance(contract, dict):
        raise policy.ContractError("contract must be a JSON object")

    if contract_kind(contract) != KIND_MCP:
        raise policy.ContractError(
            "load_mcp_contract requires upstream_kind 'mcp'; use policy.load_contract"
        )

    for key in ("provider", "upstream_url", "tools", "limits"):
        if not contract.get(key):
            raise policy.ContractError(f"contract is missing {key!r}")

    limits = contract["limits"]
    missing = [key for key in policy.REQUIRED_LIMITS if key not in limits]
    if missing:
        raise policy.ContractError(f"contract limits are missing {sorted(missing)}")
    for key in policy.REQUIRED_LIMITS:
        value = limits[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise policy.ContractError(f"limit {key!r} must be a positive integer")

    tools = contract["tools"]
    if not isinstance(tools, dict) or not tools:
        raise policy.ContractError("contract tools must be a non-empty mapping")

    mutating_enabled = bool(contract.get("mutating_tools_enabled"))
    for name, spec in tools.items():
        if not isinstance(spec, dict):
            raise policy.ContractError(f"tool {name!r} must be a mapping")
        if not isinstance(spec.get("mutating"), bool):
            raise policy.ContractError(
                f"tool {name!r} must declare a boolean 'mutating': an MCP upstream "
                f"exposes no method to infer it from"
            )
        if spec["mutating"] and not mutating_enabled:
            raise policy.ContractError(
                f"tool {name!r} is declared mutating while mutations are off, so it "
                f"could only ever be refused at call time. Advertising a tool that "
                f"cannot run is worse than not having it: a green deploy would hide "
                f"the dead surface."
            )

    if not str(contract.get("schema_sha256") or "").startswith(policy.SHA256_PREFIX):
        raise policy.ContractError("contract must pin tools.schema_sha256")

    return contract


def authorize_mcp_call(
    contract: Mapping[str, Any], name: str, arguments: Mapping[str, Any] | None
) -> str:
    """Return the upstream tool name for one call, or refuse it.

    Args:
        contract: the loaded contract.
        name: the tool the client asked for.
        arguments: the client-supplied arguments.

    The same allowlist governs listing and calling, so a client cannot reach an
    unlisted operation of the upstream by guessing its name.
    """
    spec = contract["tools"].get(name)
    if spec is None:
        raise PermissionError(f"{policy.DENY_UNKNOWN_TOOL}: {name!r}")

    if spec.get("mutating") and not contract.get("mutating_tools_enabled"):
        raise PermissionError(f"{policy.DENY_MUTATION}: {name!r} mutates")

    encoded = json.dumps(arguments or {}, separators=(",", ":"))
    if len(encoded.encode()) > contract["limits"]["request_bytes"]:
        raise PermissionError(
            f"{policy.DENY_REQUEST_TOO_LARGE}: {len(encoded)} bytes exceeds "
            f"{contract['limits']['request_bytes']}"
        )

    return name


def filter_upstream_tools(
    contract: Mapping[str, Any], upstream_tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return only those upstream descriptors the contract allows.

    Args:
        contract: the loaded contract.
        upstream_tools: the ``tools`` array of an upstream ``tools/list`` result.

    Applied to a response the upstream controls, so an upstream that starts
    serving new tools cannot widen this adapter's surface by doing so.
    """
    allowed = set(contract["tools"])
    return [
        tool
        for tool in upstream_tools
        if isinstance(tool, dict) and tool.get("name") in allowed
    ]


def undeclared_upstream_tools(
    contract: Mapping[str, Any], upstream_tools: list[dict[str, Any]]
) -> list[str]:
    """Return the names the upstream serves that the contract does not declare.

    Args:
        contract: the loaded contract.
        upstream_tools: the ``tools`` array of an upstream ``tools/list`` result.

    Drift in this direction is not refused at call time, because the adapter
    already refuses the names. It is reported so an upstream that grew a tool
    surface is noticed rather than silently filtered forever.
    """
    allowed = set(contract["tools"])
    return sorted(
        str(tool.get("name"))
        for tool in upstream_tools
        if isinstance(tool, dict) and tool.get("name") not in allowed
    )


def missing_upstream_tools(
    contract: Mapping[str, Any], upstream_tools: list[dict[str, Any]]
) -> list[str]:
    """Return contract tools the upstream no longer serves.

    Args:
        contract: the loaded contract.
        upstream_tools: the ``tools`` array of an upstream ``tools/list`` result.

    This direction must fail closed: the adapter would advertise a tool that
    cannot run, which is the dead surface the contract loader already refuses.
    """
    served = {tool.get("name") for tool in upstream_tools if isinstance(tool, dict)}
    return sorted(name for name in contract["tools"] if name not in served)
