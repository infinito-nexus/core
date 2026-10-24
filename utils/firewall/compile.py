"""Compile the agent firewall: resolve a role's includes, apply the
precedence, and answer a request.

The verdict order is deny over ask over allow, and a request that matches no
rule is denied. This module is the deterministic core the enforcement surfaces
project from (the MCP adapter policy, the egress allowlist, the LDAP groups,
the managed settings and the channel rooms); each surface is a filter of the
resolved rules by kind. Resolution and the decision are stack-free and
unit-tested here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from utils.firewall.parse import Rule, parse_rule

VERDICTS = ("deny", "ask", "allow")


@dataclass(frozen=True)
class Resolved:
    allow: tuple[Rule, ...]
    ask: tuple[Rule, ...]
    deny: tuple[Rule, ...]

    def bucket(self, verdict: str) -> tuple[Rule, ...]:
        return {"allow": self.allow, "ask": self.ask, "deny": self.deny}[verdict]


def resolve(roles: dict, name: str, _seen: frozenset[str] = frozenset()) -> Resolved:
    """Return role ``name`` with its includes folded in.

    Args:
        roles: the parsed agents/firewall/roles.yml mapping.
        name: the role to resolve.
        _seen: roles already being resolved, to stop an include cycle.
    """
    if name in _seen or name not in roles:
        return Resolved((), (), ())
    role = roles[name] or {}
    buckets: dict[str, list[Rule]] = {"allow": [], "ask": [], "deny": []}
    for included in role.get("includes") or []:
        sub = resolve(roles, included, _seen | {name})
        for verdict in VERDICTS:
            buckets[verdict].extend(sub.bucket(verdict))
    for verdict in VERDICTS:
        for raw in role.get(verdict) or []:
            buckets[verdict].append(parse_rule(raw))
    return Resolved(
        tuple(buckets["allow"]), tuple(buckets["ask"]), tuple(buckets["deny"])
    )


def _segment_regex(segment: str) -> str:
    return "[^/]*".join(re.escape(part) for part in segment.split("*"))


def _matches(rule: Rule, kind: str, target: str, action: str | None) -> bool:
    if rule.kind != kind:
        return False
    pattern = (
        "^" + "/".join(_segment_regex(seg) for seg in rule.target.split("/")) + "$"
    )
    if not re.match(pattern, target):
        return False
    if kind == "egress" or action is None:
        return True
    return action in rule.actions


def decide(
    resolved: Resolved, kind: str, target: str, action: str | None = None
) -> str:
    """Return ``deny``, ``ask`` or ``allow`` for a request.

    Deny beats ask beats allow; a request that matches no rule is denied.
    """
    for verdict in VERDICTS:
        if any(
            _matches(rule, kind, target, action) for rule in resolved.bucket(verdict)
        ):
            return verdict
    return "deny"


def egress_allowlist(resolved: Resolved) -> list[str]:
    """Return the hosts the role may reach: every allowed egress target that is
    not also denied."""
    denied = {r.target for r in resolved.deny if r.kind == "egress"}
    return sorted({r.target for r in resolved.allow if r.kind == "egress"} - denied)


def mcp_policy(resolved: Resolved) -> dict[str, list[str]]:
    """Return the per-caller policy of svc-ai-mcp-adapter: the mcp tool targets
    under each verdict, with deny over ask over allow applied so a target
    appears under only its highest-precedence verdict."""
    deny = {r.target for r in resolved.deny if r.kind == "mcp"}
    ask = {r.target for r in resolved.ask if r.kind == "mcp"} - deny
    allow = {r.target for r in resolved.allow if r.kind == "mcp"} - deny - ask
    return {"allow": sorted(allow), "ask": sorted(ask), "deny": sorted(deny)}


def ldap_groups(resolved: Resolved) -> list[str]:
    """Return the application groups the account joins: the app id of every
    allowed app grant that is not denied outright."""
    denied = {r.target.split("/")[0] for r in resolved.deny if r.kind == "app"}
    allowed = {r.target.split("/")[0] for r in resolved.allow if r.kind == "app"}
    return sorted(allowed - denied)


def managed_settings(resolved: Resolved) -> dict:
    """Return the Claude Code managed settings: the firewall verdicts as the
    read-only permission lists the workspace mounts."""
    return {
        "permissions": {
            verdict: [r.raw for r in resolved.bucket(verdict)] for verdict in VERDICTS
        }
    }


def matrix_rooms(resolved: Resolved) -> list[dict]:
    """Return the channel rooms the account joins, with a power level: a role
    that may update or delete in a room joins it with moderator power, else as
    a plain member. A denied channel is left out."""
    denied = {r.target for r in resolved.deny if r.kind == "channel"}
    rooms = []
    for rule in resolved.allow:
        if rule.kind != "channel" or rule.target in denied:
            continue
        power = "moderator" if {"update", "delete"} & rule.actions else "member"
        rooms.append({"room": rule.target, "power": power})
    return sorted(rooms, key=lambda entry: entry["room"])


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    roles = {
        "workspace": {
            "allow": ["app(workspace/worktree):crud"],
            "deny": ["app(docker/exec):crud"],
        },
        "forge-reader": {"allow": ["egress(github.com)", "app(github/runs):read"]},
        "autonomous-contributor": {
            "includes": ["workspace", "forge-reader"],
            "allow": ["app(fork/push):create"],
            "ask": ["app(fork/force-push):create"],
            "deny": ["app(upstream/push):create", "app(repo/protected-paths):update"],
        },
        "maintainer": {"includes": ["autonomous-contributor"]},
    }
    r = resolve(roles, "maintainer")
    _expect(
        decide(r, "egress", "github.com") == "allow", "inherited egress not allowed"
    )
    _expect(
        decide(r, "app", "github/runs", "read") == "allow",
        "github/runs read not allowed",
    )
    _expect(
        decide(r, "app", "fork/push", "create") == "allow",
        "fork/push create not allowed",
    )
    _expect(
        decide(r, "app", "fork/force-push", "create") == "ask", "force-push not ask"
    )
    _expect(
        decide(r, "app", "upstream/push", "create") == "deny",
        "upstream push not denied",
    )
    _expect(
        decide(r, "app", "repo/protected-paths", "update") == "deny",
        "protected-paths update not denied",
    )
    _expect(
        decide(r, "app", "docker/exec", "create") == "deny", "docker exec not denied"
    )
    _expect(
        decide(r, "egress", "evil.example") == "deny", "unmatched egress not denied"
    )
    _expect(
        decide(r, "app", "github/runs", "delete") == "deny",
        "unlisted action not denied",
    )
    _expect(egress_allowlist(r) == ["github.com"], egress_allowlist(r))

    wild = {"r": {"allow": ["egress(*.example.com)", "egress(api.*)"]}}
    w = resolve(wild, "r")
    _expect(
        decide(w, "egress", "api.example.com") == "allow", "embedded * subdomain missed"
    )
    _expect(decide(w, "egress", "example.com") == "deny", "bare apex wrongly allowed")
    _expect(decide(w, "egress", "api.internal") == "allow", "trailing * missed")
    _expect(decide(w, "egress", "evil.org") == "deny", "unrelated host allowed")

    surfaces = {
        "planner": {
            "allow": [
                "mcp(openproject/work_packages):crud",
                "mcp(shell/run):read",
                "app(web-app-openproject/board):read",
                "channel(web-app-matrix/team):create+read+update",
            ],
            "deny": ["channel(web-app-matrix/secret):read", "mcp(shell/run):read"],
        }
    }
    p = resolve(surfaces, "planner")
    _expect(mcp_policy(p)["allow"] == ["openproject/work_packages"], mcp_policy(p))
    _expect(
        mcp_policy(p)["deny"] == ["shell/run"], "deny precedence not applied to mcp"
    )
    _expect(ldap_groups(p) == ["web-app-openproject"], ldap_groups(p))
    _expect(
        matrix_rooms(p) == [{"room": "web-app-matrix/team", "power": "moderator"}],
        matrix_rooms(p),
    )
    _expect(
        "channel(web-app-matrix/secret):read"
        in managed_settings(p)["permissions"]["deny"],
        "denied channel missing from managed settings",
    )
    print("firewall compile self-check ok")


if __name__ == "__main__":
    _demo()
