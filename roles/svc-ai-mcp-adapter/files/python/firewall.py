"""Firewall layer of the reusable MCP adapter.

An agent's ``tools/call`` is decided by that agent's compiled firewall policy,
the ``mcp_policy`` surface of utils/firewall/compile.py, on the target
``<provider>/<tool>``: deny beats ask beats allow, and a call no rule matches
is denied. Like :mod:`policy` this module is pure: it decides, it does not
perform I/O.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

DENY_FIREWALL = "firewall_refused"

UNMATCHED_RULE = "no rule matched"
FIREWALL_VERDICTS = ("deny", "ask", "allow")
METHOD_ACTIONS = {
    "GET": "read",
    "HEAD": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


def tool_action(spec: Mapping[str, Any]) -> str:
    """Return the firewall action of one tool: its HTTP method's action, an
    unknown method counted as ``update``, or for an MCP upstream tool
    ``update`` when it mutates and ``read`` otherwise.

    Args:
        spec: the tool's contract entry.
    """
    if "method" in spec:
        return METHOD_ACTIONS.get(str(spec["method"]).upper(), "update")
    return "update" if spec.get("mutating") else "read"


def _target_matches(pattern: str, target: str) -> bool:
    regex = "/".join(
        "[^/]*".join(re.escape(part) for part in segment.split("*"))
        for segment in pattern.split("/")
    )
    return re.fullmatch(regex, target) is not None


def firewall_verdict(
    agent_policy: Mapping[str, Any], target: str, action: str
) -> tuple[str, str]:
    """Return ``(verdict, rule)`` for one call: deny beats ask beats allow,
    the rule is the first matching one of the winning verdict, and a call no
    rule matches is denied by ``UNMATCHED_RULE``.

    Args:
        agent_policy: the agent's compiled ``mcp_policy``, each verdict a list
            of ``{"rule", "target", "actions"}``.
        target: ``<provider>/<tool>``.
        action: the call's action from ``tool_action``.
    """
    for verdict in FIREWALL_VERDICTS:
        for rule in agent_policy.get(verdict) or []:
            if action in rule["actions"] and _target_matches(rule["target"], target):
                return verdict, rule["rule"]
    return "deny", UNMATCHED_RULE


def authorize_agent_call(
    agent_policy: Mapping[str, Any], provider: str, name: str, spec: Mapping[str, Any]
) -> str:
    """Return the rule that grants an agent's tool call, or refuse the call
    naming the rule that matched.

    Args:
        agent_policy: the calling agent's compiled ``mcp_policy``.
        provider: the contract's provider.
        name: the tool the agent asked for.
        spec: that tool's contract entry.

    An ``ask`` is refused too: the adapter is no gate node, so an ask met here
    is a firewall misconfiguration, never a silent allow.
    """
    verdict, rule = firewall_verdict(
        agent_policy, f"{provider}/{name}", tool_action(spec)
    )
    if verdict != "allow":
        raise PermissionError(f"{DENY_FIREWALL}: {verdict} by {rule}")
    return rule


def authorize_request(
    contract: Mapping[str, Any],
    policies: Mapping[str, Any],
    request: Mapping[str, Any],
    agent: str,
) -> None:
    """Refuse an agent's ``tools/call`` outside its firewall grants.

    Args:
        contract: the loaded contract.
        policies: agent account to its compiled ``mcp_policy``.
        request: the decoded JSON-RPC request object.
        agent: the authenticated agent account.
    """
    if request.get("method") != "tools/call":
        return
    name = str((request.get("params") or {}).get("name") or "")
    spec = contract["tools"].get(name)
    if spec is None:
        return
    authorize_agent_call(policies.get(agent) or {}, contract["provider"], name, spec)
