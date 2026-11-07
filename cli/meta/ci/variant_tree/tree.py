"""Build and render the variant tree of one CI row."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cli.meta.ci.variant_split.edges import is_active
from cli.meta.ci.variant_split.rounds import (
    base_services,
    pins_in_force,
    service_registry,
    settle,
)
from utils.roles.applications.topics import provider_of
from utils.roles.applications.variant_pins import VariantPinError


def parse_token(tok: str) -> tuple[str, int]:
    """Split ``role#variant``; a bare role means variant 0.

    Args:
        tok: the row token.

    Raises:
        ValueError: the variant part is not a number.
    """
    name, _, variant = tok.partition("#")
    if variant and not variant.isdigit():
        raise ValueError(f"{tok!r}: the variant after '#' must be a number")
    return name, int(variant or 0)


def reason(
    role: str, *, primary: str, index: int, count: int, pinned: Mapping[str, str]
) -> str:
    """Why the round runs *role* in the variant it does.

    Args:
        role: the node.
        primary: the row's primary role.
        index: the row's round index.
        count: how many variants *role* declares.
        pinned: role -> the ``carrier#index`` whose pin in force moves it.
    """
    if role == primary:
        return "primary"
    if role in pinned:
        return f"pin by {pinned[role]}"
    if index < count:
        return "round index"
    return "default 0: round past its variants"


def state(entry: Any, base_entry: Any) -> str:
    """How a service key of a node is switched in this round.

    Args:
        entry: the key's entry in the round's services map.
        base_entry: the key's entry in the role's ``meta/services.yml``.
    """
    if not is_active(entry):
        return "off"
    enabled = entry.get("enabled")
    if enabled is True:
        base_on = isinstance(base_entry, Mapping) and base_entry.get("enabled") is True
        return "required" if base_on else "forced by override"
    if isinstance(enabled, str) and "group_names" in enabled:
        return "presence-gated"
    if enabled is None:
        return "implicit"
    return "templated"


def build(
    tok: str, *, roles_dir: str, variants_per_app: Mapping[str, list]
) -> dict[str, Any]:
    """The variant tree of one row, in plain JSON types.

    Args:
        tok: the row's ``role#variant`` token.
        roles_dir: the roles tree.
        variants_per_app: parsed variants per role.

    Raises:
        ValueError: the role is not in the tree, or it declares no variant at
            that index.
    """
    name, index = parse_token(tok)
    if name not in variants_per_app:
        raise ValueError(f"{tok!r}: no role {name!r} in the roles tree")
    declared = max(1, len(variants_per_app[name] or []))
    if index >= declared:
        raise ValueError(
            f"{tok!r}: {name} declares {declared} variant(s), so the variant "
            f"after '#' must be 0..{declared - 1}"
        )
    head = {"primary": f"{name}#{index}", "round_index": index}
    try:
        include, maps, active = settle(
            name, index, roles_dir=roles_dir, variants_per_app=variants_per_app
        )
    except VariantPinError as exc:
        return {**head, "include_count": 0, "error": str(exc), "nodes": []}
    pinned = pins_in_force(include, active, roles_dir=roles_dir)
    registry = service_registry(roles_dir)
    nodes = []
    for role in include:
        count = len(variants_per_app.get(role) or [])
        base = base_services(role, roles_dir)
        services_map = maps.get(role)
        services = []
        for key, entry in (
            sorted((services_map or {}).items())
            if isinstance(services_map, Mapping)
            else []
        ):
            provider = provider_of(str(key), registry)
            if not provider or provider == role:
                continue
            services.append(
                {
                    "key": str(key),
                    "provider": provider,
                    "state": state(entry, base.get(key)),
                    "deployed": provider in include,
                }
            )
        nodes.append(
            {
                "role": role,
                "variant": active[role],
                "variants": max(count, 1),
                "reason": reason(
                    role, primary=name, index=index, count=count, pinned=pinned
                ),
                "services": services,
                "children": sorted(
                    {
                        s["provider"]
                        for s in services
                        if s["deployed"] and s["state"] != "off"
                    }
                ),
            }
        )
    return {**head, "include_count": len(include), "error": None, "nodes": nodes}


def render_text(tree: Mapping[str, Any]) -> str:
    """The tree as indented text, each node once, later visits referenced.

    Args:
        tree: a tree :func:`build` produced, optionally with ``axes``.
    """
    lines = [
        f"{tree['primary']}: include {tree['include_count']} (resolve_round), round index {tree['round_index']}"
    ]
    if tree.get("error"):
        return "\n".join([*lines, f"error: {tree['error']}"])
    for sweep, facts in sorted((tree.get("axes") or {}).items()):
        lines.append(
            f"sweep {sweep}: {facts['entries']} job position {facts['job_position']}, "
            f"in budget head {facts['in_budget_head']}, covered {facts['covered']}"
        )
    nodes = {node["role"]: node for node in tree["nodes"]}
    seen: set[str] = set()

    def walk(role: str, depth: int) -> None:
        node = nodes[role]
        pad = "  " * depth
        label = f"{pad}{role}#{node['variant']}/{node['variants']} [{node['reason']}]"
        if role in seen:
            lines.append(f"{label} (above)")
            return
        seen.add(role)
        lines.append(label)
        for svc in node["services"]:
            mark = "" if svc["deployed"] else " (not deployed)"
            lines.append(
                f"{pad}  . {svc['key']} -> {svc['provider']}: {svc['state']}{mark}"
            )
        for child in node["children"]:
            walk(child, depth + 1)

    primary = tree["primary"].split("#", 1)[0]
    if primary in nodes:
        walk(primary, 0)
    for role in nodes:
        if role not in seen:
            walk(role, 0)
    return "\n".join(lines)
