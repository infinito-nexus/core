"""Policy layer of the reusable MCP adapter.

One adapter process fronts exactly one provider application. It never mirrors
that provider's API: it exposes the operations named in a checked-in allowlist
and nothing else, and it enforces that allowlist on ``tools/call`` as well as
on ``tools/list``. Filtering only the listing would leave every unlisted
operation callable by name.

The contract arrives as one JSON document (``ADAPTER_CONTRACT``) so the same
image serves every provider; the deployment renders a different contract per
instance.

This module is pure: it decides, it does not perform I/O. That keeps the rules
testable without a live upstream.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REQUIRED_LIMITS = (
    "request_bytes",
    "response_bytes",
    "timeout_seconds",
    "concurrent_requests",
    "page_size",
    "result_items",
    "stream_seconds",
)

SHA256_PREFIX = "sha256:"

DENY_UNKNOWN_TOOL = "unknown_tool"
DENY_MUTATION = "mutation_not_enabled"
DENY_REQUEST_TOO_LARGE = "request_too_large"
DENY_SCHEMA_DRIFT = "schema_drift"
DENY_UNAUTHENTICATED = "unauthenticated"

READ_METHODS = frozenset({"GET", "HEAD"})


class ContractError(ValueError):
    """The rendered contract is not one this adapter may serve."""


def load_contract(raw: str) -> dict[str, Any]:
    """Return the validated adapter contract.

    Args:
        raw: the ``ADAPTER_CONTRACT`` JSON document.

    A contract missing a limit, an allowlist or a schema hash is rejected at
    startup rather than at the first call, so a misconfigured instance never
    reaches a client.
    """
    try:
        contract = json.loads(raw or "{}")
    except json.JSONDecodeError as error:
        raise ContractError(f"contract is not JSON: {error}") from error
    if not isinstance(contract, dict):
        raise ContractError("contract must be a JSON object")

    for key in ("provider", "upstream_url", "tools", "limits"):
        if not contract.get(key):
            raise ContractError(f"contract is missing {key!r}")

    limits = contract["limits"]
    missing = [key for key in REQUIRED_LIMITS if key not in limits]
    if missing:
        raise ContractError(f"contract limits are missing {sorted(missing)}")
    for key in REQUIRED_LIMITS:
        value = limits[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContractError(f"limit {key!r} must be a positive integer")

    tools = contract["tools"]
    if not isinstance(tools, dict) or not tools:
        raise ContractError("contract tools must be a non-empty mapping")
    for name, spec in tools.items():
        if not isinstance(spec, dict):
            raise ContractError(f"tool {name!r} must be a mapping")
        for key in ("method", "path"):
            if not spec.get(key):
                raise ContractError(f"tool {name!r} is missing {key!r}")
        if "*" in str(spec["path"]):
            raise ContractError(f"tool {name!r} declares a wildcard path")
        if str(spec["method"]).upper() not in READ_METHODS and not contract.get(
            "mutating_tools_enabled"
        ):
            raise ContractError(
                f"tool {name!r} declares {spec['method']!r} while mutations are "
                f"off, so it could only ever be refused at call time. Advertising "
                f"a tool that cannot run is worse than not having it: a green "
                f"deploy would hide the dead surface."
            )

    if not str(contract.get("schema_sha256") or "").startswith(SHA256_PREFIX):
        raise ContractError("contract must pin tools.schema_sha256")

    return contract


def schema_digest(tools: Mapping[str, Any]) -> str:
    """Return the canonical hash of a tool contract.

    Args:
        tools: the tool mapping to digest.
    """
    canonical = json.dumps(tools, sort_keys=True, separators=(",", ":"))
    return SHA256_PREFIX + hashlib.sha256(canonical.encode()).hexdigest()


def assert_no_drift(contract: Mapping[str, Any]) -> None:
    """Fail closed when the tool contract no longer matches its pinned hash.

    Args:
        contract: the loaded contract.
    """
    found = schema_digest(contract["tools"])
    if found != contract["schema_sha256"]:
        raise ContractError(
            f"{DENY_SCHEMA_DRIFT}: tools hash {found} does not match the "
            f"pinned {contract['schema_sha256']}"
        )


def listed_tools(contract: Mapping[str, Any]) -> list[str]:
    """Return the tool names this adapter advertises, in a stable order.

    Args:
        contract: the loaded contract.
    """
    return sorted(contract["tools"])


def authorize_client(expected: str, presented: str) -> None:
    """Refuse a caller that did not present the adapter's own bearer.

    Args:
        expected: the bearer this instance was issued.
        presented: the ``Authorization`` header value the caller sent.

    The upstream credential authenticates the adapter *to* the provider. It
    says nothing about who called the adapter, which is exactly the gap the
    project-owned MCP sidecars leave open.
    """
    prefix = "Bearer "
    token = presented[len(prefix) :] if presented.startswith(prefix) else ""
    if not expected or not token or token != expected:
        raise PermissionError(DENY_UNAUTHENTICATED)


def authorize_call(
    contract: Mapping[str, Any], name: str, arguments: Mapping[str, Any] | None
) -> tuple[str, str]:
    """Return the upstream ``(method, path)`` for one tool call, or refuse it.

    Args:
        contract: the loaded contract.
        name: the tool the client asked for.
        arguments: the client-supplied arguments.

    Raises ``PermissionError`` with a stable reason for anything the contract
    does not name. The same check runs here and on listing, so a client cannot
    reach an operation by guessing its name.
    """
    spec = contract["tools"].get(name)
    if spec is None:
        raise PermissionError(f"{DENY_UNKNOWN_TOOL}: {name!r}")

    method = str(spec["method"]).upper()
    if method not in READ_METHODS and not contract.get("mutating_tools_enabled"):
        raise PermissionError(f"{DENY_MUTATION}: {name!r} is {method}")

    encoded = json.dumps(arguments or {}, separators=(",", ":"))
    if len(encoded.encode()) > contract["limits"]["request_bytes"]:
        raise PermissionError(
            f"{DENY_REQUEST_TOO_LARGE}: {len(encoded)} bytes exceeds "
            f"{contract['limits']['request_bytes']}"
        )

    return method, str(spec["path"])


def clamp_page(contract: Mapping[str, Any], requested: Any) -> int:
    """Return a page size no larger than the contract allows.

    Args:
        contract: the loaded contract.
        requested: whatever the client asked for.
    """
    ceiling = contract["limits"]["page_size"]
    try:
        wanted = int(requested)
    except (TypeError, ValueError):
        return ceiling
    return max(1, min(wanted, ceiling))


def truncate_results(contract: Mapping[str, Any], items: Sequence[Any]) -> list[Any]:
    """Return at most the contract's result ceiling.

    Args:
        contract: the loaded contract.
        items: the upstream result rows.
    """
    return list(items[: contract["limits"]["result_items"]])


def audit_event(
    contract: Mapping[str, Any],
    consumer: str,
    tool: str,
    status: str,
    duration_ms: int,
    correlation_id: str,
) -> dict[str, Any]:
    """Return one audit record for a call.

    Args:
        contract: the loaded contract.
        consumer: the calling client's application id.
        tool: the tool name.
        status: ``ok`` or a deny reason.
        duration_ms: wall time of the upstream call.
        correlation_id: identifier tying the record to the client request.

    Carries who, what and how it ended. Never the arguments, never the
    response body and never the credential: an audit log that leaks the
    payload is a second copy of the data it is meant to guard.
    """
    return {
        "provider": contract["provider"],
        "consumer": consumer,
        "tool": tool,
        "subject": contract.get("auth_subject"),
        "status": status,
        "duration_ms": duration_ms,
        "correlation_id": correlation_id,
    }
