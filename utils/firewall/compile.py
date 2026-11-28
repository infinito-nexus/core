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

import json
import re
from dataclasses import dataclass

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.firewall.parse import Rule, parse_rule, substitute

VERDICTS = ("deny", "ask", "allow")
MISCONFIGURATION = "misconfiguration"
WRITE_ACTIONS = frozenset({"create", "update", "delete"})
WRITE_GATE_SCENARIOS = ("deny", "kill-switch", "audit", "identity")
LOCAL_APPS = ("workspace",)
SETTINGS_KIND = "tool"


@dataclass(frozen=True)
class Resolved:
    allow: tuple[Rule, ...]
    ask: tuple[Rule, ...]
    deny: tuple[Rule, ...]

    def bucket(self, verdict: str) -> tuple[Rule, ...]:
        return {"allow": self.allow, "ask": self.ask, "deny": self.deny}[verdict]


def _settings_rules(path: str) -> dict[str, list[Rule]]:
    """Return the permission lists of a Claude Code settings file as rules.

    Args:
        path: the settings file, relative to the repository root.

    Returns:
        Per verdict, one ``SETTINGS_KIND`` rule per entry of the file's
        ``permissions`` list, verbatim and in the file's order.
    """
    permissions = json.loads(read_text(str(PROJECT_ROOT / path)))["permissions"]
    return {
        verdict: [
            Rule(kind=SETTINGS_KIND, target=raw, actions=frozenset(), raw=raw)
            for raw in permissions.get(verdict) or []
        ]
        for verdict in VERDICTS
    }


def resolve(roles: dict, name: str, _seen: frozenset[str] = frozenset()) -> Resolved:
    """Return role ``name`` with its includes folded in.

    Args:
        roles: the parsed agents/firewall/roles.yml mapping; a role's
            ``settings`` names a Claude Code settings file, relative to the
            repository root, whose permission lists join that role's verdicts.
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
    if role.get("settings"):
        for verdict, rules in _settings_rules(role["settings"]).items():
            buckets[verdict].extend(rules)
    return Resolved(
        tuple(buckets["allow"]), tuple(buckets["ask"]), tuple(buckets["deny"])
    )


def _segment_regex(segment: str) -> str:
    return "[^/]*".join(re.escape(part) for part in segment.split("*"))


def _matches(rule: Rule, kind: str, target: str, action: str | None) -> bool:
    if rule.kind != kind:
        return False
    if kind == SETTINGS_KIND:
        return rule.target == target
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


def expand(resolved: Resolved, variables: dict[str, str]) -> Resolved:
    """Return ``resolved`` with every ``${VAR}`` in a rule target replaced by
    its deploy variable, so a rule like
    ``egress(${INFINITO_BIND_IP}:${INFINITO_TOOLS_LIBRETRANSLATE_PORT})``
    grants the address the deploy renders.

    Args:
        resolved: a resolved firewall role.
        variables: the deploy variables by name.

    Raises:
        KeyError: a rule names a variable the deploy does not set.
    """

    def _expanded(rule: Rule) -> Rule:
        if rule.kind == SETTINGS_KIND or not rule.variables:
            return rule
        missing = sorted(rule.variables - set(variables))
        if missing:
            raise KeyError(f"rule {rule.raw!r}: no deploy variable {missing}")
        return parse_rule(substitute(rule.raw, variables))

    return Resolved(
        tuple(map(_expanded, resolved.allow)),
        tuple(map(_expanded, resolved.ask)),
        tuple(map(_expanded, resolved.deny)),
    )


def write_gate(
    resolved: Resolved, *, write_enabled: bool, scenarios_passed: dict[str, bool]
) -> Resolved:
    """Return ``resolved`` without any write grant unless the agent may write.

    A write grant is a ``create``, ``update`` or ``delete`` on anything that
    leaves the agent's own workspace (push, comment, email, ticket reply, work
    package write). It survives only with ``write_enabled`` and every gate
    scenario passed for the deployed revision; otherwise the allow and ask
    rules keep their read action alone, and a rule left without an action is
    dropped, as is every ``SETTINGS_KIND`` rule, which names no action to keep.
    Deny rules and egress are untouched.

    Args:
        resolved: a resolved firewall role.
        write_enabled: the agent's ``write_enabled`` field.
        scenarios_passed: the result of each gate scenario by name, one of
            ``WRITE_GATE_SCENARIOS``.
    """
    if write_enabled and all(
        scenarios_passed.get(name) is True for name in WRITE_GATE_SCENARIOS
    ):
        return resolved

    def _read_only(rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
        kept: list[Rule] = []
        for rule in rules:
            if rule.kind == SETTINGS_KIND:
                continue
            local = rule.target.split("/")[0] in LOCAL_APPS
            if rule.kind == "egress" or local or not rule.actions & WRITE_ACTIONS:
                kept.append(rule)
                continue
            actions = rule.actions - WRITE_ACTIONS
            if actions:
                kept.append(
                    Rule(
                        kind=rule.kind,
                        target=rule.target,
                        actions=actions,
                        raw=f"{rule.kind}({rule.target}):{'+'.join(sorted(actions))}",
                    )
                )
        return tuple(kept)

    return Resolved(_read_only(resolved.allow), _read_only(resolved.ask), resolved.deny)


def decide_intersection(
    profile: Resolved,
    owner: Resolved,
    kind: str,
    target: str,
    action: str | None = None,
) -> str:
    """Return the verdict for a user-started agent: the intersection of its
    profile's grants and its owner's rights. The stricter verdict of the two
    wins, so the agent gets nothing its owner lacks.

    Args:
        profile: the resolved firewall role of the agent's profile.
        owner: the owner's rights, resolved the same way.
        kind: the request kind.
        target: the request target.
        action: the request action, ``None`` for egress.
    """
    verdicts = (
        decide(profile, kind, target, action),
        decide(owner, kind, target, action),
    )
    return min(verdicts, key=VERDICTS.index)


def at_step(verdict: str, step_kind: str) -> str:
    """Return the verdict a routine step acts on: an ``ask`` met anywhere but
    at a declared gate node (a step of kind ``ask``) is a firewall
    misconfiguration, reported instead of asked.

    Args:
        verdict: the firewall's ``deny``, ``ask`` or ``allow``.
        step_kind: the kind of the routine step that made the request.
    """
    if verdict == "ask" and step_kind != "ask":
        return MISCONFIGURATION
    return verdict


def account_grants(roles: dict, firewall_roles: list[str]) -> list[str]:
    """Return an agent's allowed ``account`` grants in their order: the order
    of its ``firewall_roles`` binding, then the rule order inside each role.
    The first active one is the agent's default account.

    Args:
        roles: the parsed agents/firewall/roles.yml mapping.
        firewall_roles: the agent's bound firewall roles, in order.
    """
    ordered: list[str] = []
    for name in firewall_roles:
        for rule in resolve(roles, name).allow:
            if rule.kind == "account" and rule.target not in ordered:
                ordered.append(rule.target)
    return ordered


def egress_allowlist(resolved: Resolved) -> list[str]:
    """Return the hosts the role may reach: every allowed egress target that is
    not also denied."""
    denied = {r.target for r in resolved.deny if r.kind == "egress"}
    return sorted({r.target for r in resolved.allow if r.kind == "egress"} - denied)


def narrow(resolved: Resolved, override: dict) -> Resolved:
    """Return ``resolved`` with an inventory or Open WebUI override folded in,
    refusing every override rule that could widen a verdict. An override may
    add ``deny`` rules, and ``ask`` rules only on a target a base ``allow``
    rule of the same kind grants verbatim with at least those actions; an
    override ``allow``, ``includes`` or any other key is refused.

    Args:
        resolved: the agent's resolved firewall role.
        override: the override mapping, keys ``ask`` and ``deny``.

    Raises:
        PermissionError: an override rule or key could widen a verdict.
    """
    widening = sorted(set(override) - {"ask", "deny"})
    if widening:
        raise PermissionError(f"override keys {widening} could widen the firewall")
    asks: list[Rule] = []
    for raw in override.get("ask") or []:
        rule = parse_rule(raw)
        if not any(
            base.kind == rule.kind
            and base.target == rule.target
            and rule.actions <= base.actions
            for base in resolved.allow
        ):
            raise PermissionError(f"override ask {raw!r} asks for what no allow grants")
        asks.append(rule)
    denies = tuple(parse_rule(raw) for raw in override.get("deny") or [])
    return Resolved(resolved.allow, resolved.ask + tuple(asks), resolved.deny + denies)


def mcp_policy(resolved: Resolved) -> dict[str, list[dict]]:
    """Return the per-caller policy of svc-ai-mcp-adapter: every mcp rule under
    its verdict as ``{"rule", "target", "actions"}``, in rule order. The
    adapter answers a tool call from it exactly as ``decide`` answers the
    request, deny over ask over allow and unmatched denied, and names the
    matched rule."""
    return {
        verdict: [
            {"rule": r.raw, "target": r.target, "actions": sorted(r.actions)}
            for r in resolved.bucket(verdict)
            if r.kind == "mcp"
        ]
        for verdict in VERDICTS
    }


def ldap_groups(resolved: Resolved) -> list[str]:
    """Return the application groups the account joins: the app id of every
    allowed app grant that is not denied outright."""
    denied = {r.target.split("/")[0] for r in resolved.deny if r.kind == "app"}
    allowed = {r.target.split("/")[0] for r in resolved.allow if r.kind == "app"}
    return sorted(allowed - denied)


def managed_settings(resolved: Resolved) -> dict:
    """Return the Claude Code managed settings the workspace mounts read-only.

    Args:
        resolved: a resolved firewall role.

    Returns:
        The ``permissions`` lists: per verdict, the raw text of every
        ``SETTINGS_KIND`` rule of ``resolved``, in order.
    """
    return {
        "permissions": {
            verdict: [
                r.raw for r in resolved.bucket(verdict) if r.kind == SETTINGS_KIND
            ]
            for verdict in VERDICTS
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
    _expect(
        [r["target"] for r in mcp_policy(p)["allow"]]
        == ["openproject/work_packages", "shell/run"],
        mcp_policy(p),
    )
    _expect(
        mcp_policy(p)["deny"]
        == [
            {"rule": "mcp(shell/run):read", "target": "shell/run", "actions": ["read"]}
        ],
        "denied mcp rule missing",
    )
    _expect(ldap_groups(p) == ["web-app-openproject"], ldap_groups(p))
    _expect(
        matrix_rooms(p) == [{"room": "web-app-matrix/team", "power": "moderator"}],
        matrix_rooms(p),
    )
    _expect(
        managed_settings(p) == {"permissions": {v: [] for v in VERDICTS}},
        "firewall rules leaked into the managed settings",
    )
    edit = Rule(kind=SETTINGS_KIND, target="Edit", actions=frozenset(), raw="Edit")
    tools = Resolved(allow=(edit,), ask=(), deny=())
    _expect(
        managed_settings(tools)["permissions"]["allow"] == ["Edit"],
        managed_settings(tools),
    )
    _expect(decide(tools, SETTINGS_KIND, "Edit") == "allow", "tool rule not matched")
    _expect(
        decide(tools, SETTINGS_KIND, "Edit(x)") == "deny",
        "tool rule matched beyond its text",
    )
    _expect(
        managed_settings(write_gate(tools, write_enabled=False, scenarios_passed={}))[
            "permissions"
        ]["allow"]
        == [],
        "tool rule kept without the write gate",
    )
    print("firewall compile self-check ok")


if __name__ == "__main__":
    _demo()
