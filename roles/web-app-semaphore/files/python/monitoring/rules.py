from __future__ import annotations

import ast

MARKER = "infinito-nexus monitoring"
ICMP_RULESET = "active_checks:icmp"
HTTP_RULESET = "active_checks:httpv2"
RULESETS = (ICMP_RULESET, HTTP_RULESET)
AGENT_TAG = "tag_agent"
AGENT_ON = "cmk-agent"
AGENT_OFF = "no-agent"
SSH_LABELS = {
    "user": "infinito/ssh_user",
    "port": "infinito/ssh_port",
    "key_type": "infinito/ssh_host_key_type",
    "key": "infinito/ssh_host_key",
}
DAY_SECONDS = 86400
# Exception: 1 MiB caps a value_raw before ast.literal_eval parses it: the HTTPS rule holds one endpoint of at most ~330 characters per instance domain, so even thousands of domains stay below it; a longer value_raw is not ours and is never parsed.
VALUE_RAW_LIMIT = 1048576
UNREADABLE = (SyntaxError, ValueError, TypeError, MemoryError, RecursionError)


def host_attributes(workspace, host, entry):
    """Args:
    workspace: ``ws-<id>``.
    host: the inventory host.
    entry: its plan entry.

    Returns:
        The Checkmk attributes of the host: address, the labels ``workspace``
        and ``instance``, the SSH access labels the platform's agent
        datasource reads for an agent host, and the agent tag; no personal
        data.
    """
    labels = {"workspace": workspace, "instance": host}
    if entry["share"]["agent"]:
        labels.update({SSH_LABELS[key]: entry["ssh"][key] for key in SSH_LABELS})
    return {
        "ipaddress": entry["address"],
        "labels": labels,
        AGENT_TAG: AGENT_ON if entry["share"]["agent"] else AGENT_OFF,
    }


def rule_prefix(workspace, host):
    return f"{MARKER} {workspace} {host} "


def desired_rules(workspace, host, entry, tls_days):
    """Args:
    workspace: ``ws-<id>``.
    host: the inventory host.
    entry: its plan entry.
    tls_days: ``(warn, crit)`` days of the TLS expiry check.

    Returns:
        ``{description: (ruleset, value)}``: with ``reachability`` an ICMP
        check and one HTTPS check per domain that also checks the certificate
        expiry against ``tls_days``; nothing without it.
    """
    if not entry["share"]["reachability"]:
        return {}
    warn, crit = (float(days * DAY_SECONDS) for days in tls_days)
    prefix = rule_prefix(workspace, host)
    rules = {f"{prefix}icmp": (ICMP_RULESET, {})}
    if entry["domains"]:
        rules[f"{prefix}https"] = (
            HTTP_RULESET,
            {
                "endpoints": [
                    {
                        "service_name": {"prefix": "auto", "name": domain},
                        "url": f"https://{domain}/",
                    }
                    for domain in entry["domains"]
                ],
                "standard_settings": {"cert": ("validate", ("fixed", (warn, crit)))},
            },
        )
    return rules


def rule_conditions(name):
    return {"host_name": {"match_on": [name], "operator": "one_of"}}


def rule_value(rule):
    """Args:
    rule: a rule as the Checkmk REST API lists it.

    Returns:
        Its ``value_raw`` parsed as a Python literal, None when it is no
        string, longer than ``VALUE_RAW_LIMIT`` or unreadable.
    """
    raw = (rule.get("extensions") or {}).get("value_raw") or ""
    if not isinstance(raw, str) or len(raw) > VALUE_RAW_LIMIT:
        return None
    try:
        return ast.literal_eval(raw)
    except UNREADABLE:
        return None


def rule_description(rule):
    """Args:
    rule: a rule as the Checkmk REST API lists it.

    Returns:
        Its description, empty when it has none.
    """
    extensions = rule.get("extensions") or {}
    return (extensions.get("properties") or {}).get("description") or ""
