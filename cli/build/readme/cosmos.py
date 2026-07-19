"""Derive a Cosmos mermaid flowchart from every role's ``meta/services.yml``.

The role box lists EVERY service the role declares. Around it:

  Dependencies  roles this role consumes, on the left. A consumption is a
                service whose ``enabled``/``shared`` flag names another role
                (``'<role>' in group_names``) or whose key matches another
                role's ``provides`` (provision) name.
  Dependents    roles that consume THIS role, on the right. The mirror of the
                above: another role names this one, or declares a service keyed
                by this role's ``provides`` name (e.g. web-app-keycloak
                ``provides: sso`` and every role with an ``sso`` service).

``provides`` matching runs in both directions, so a provider (e.g. openldap
``provides: ldap``) is picked up even when the consuming flag uses a
``groups[...]`` form the ``group_names`` regex cannot read.

Edge style encodes the flag: a solid edge is a fixed (literal ``true``)
relationship, a dashed edge is variable (a ``{{ ... }}`` conditional).

``run_after`` is deliberately NOT read: it is a deploy-ordering hint, not a
runtime dependency. The wider cosmos (federation peers, external bridged
networks) cannot be derived from metadata and is left for the author to add.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.deploy import role_deploy_modes
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_META_SERVICES
from utils.symbol_glossary import to_emoji

_GROUP_DEP_RE = re.compile(r"'([a-z0-9][a-z0-9-]*)'\s+in\s+group_names")
_DEPENDENTS_CAP = 12
_MERMAID_RESERVED = {
    "call",
    "class",
    "click",
    "default",
    "end",
    "graph",
    "style",
    "subgraph",
}


def _node_id(raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not safe or safe[0].isdigit():
        safe = f"n_{safe}"
    if safe in _MERMAID_RESERVED:
        safe = f"{safe}_n"
    return safe


def _flag_kind(entry: dict) -> str | None:
    """Classify a service's enablement: ``fixed``, ``variable`` or ``None``.

    fixed     at least one of enabled/shared is a literal bool.
    variable  at least one is a ``{{ ... }}`` string (conditional).
    None      neither enabled nor shared is present.
    """
    present = [entry.get("enabled"), entry.get("shared")]
    present = [v for v in present if v is not None]
    if not present:
        return None
    return "variable" if any(isinstance(v, str) for v in present) else "fixed"


def _group_refs(entry: dict) -> set[str]:
    refs: set[str] = set()
    for flag in (entry.get("enabled"), entry.get("shared")):
        if isinstance(flag, str):
            refs.update(_GROUP_DEP_RE.findall(flag))
    return refs


def _provides_of(services: dict) -> set[str]:
    out: set[str] = set()
    for entry in services.values():
        if isinstance(entry, dict):
            prov = entry.get("provides")
            if isinstance(prov, str) and prov.strip():
                out.add(prov.strip())
    return out


@functools.lru_cache(maxsize=1)
def _roles_meta(roles_root_str: str) -> dict[str, dict]:
    """Load and cache every role's ``meta/services.yml`` mapping once."""
    roles_root = Path(roles_root_str)
    meta: dict[str, dict] = {}
    for role_dir in sorted(roles_root.iterdir()):
        services_path = role_dir / ROLE_FILE_META_SERVICES
        if not (role_dir.is_dir() and services_path.is_file()):
            continue
        loaded = load_yaml_any(str(services_path), default_if_missing={})
        meta[role_dir.name] = loaded if isinstance(loaded, dict) else {}
    return meta


@functools.lru_cache(maxsize=1)
def _roles_ansible_deps(roles_root_str: str) -> dict[str, set[str]]:
    """Every role's ``meta/main.yml`` ``dependencies`` (string or
    ``{role: ...}`` entries), cached once."""
    roles_root = Path(roles_root_str)
    deps: dict[str, set[str]] = {}
    for role_dir in sorted(roles_root.iterdir()):
        main_path = role_dir / ROLE_FILE_META_MAIN
        if not (role_dir.is_dir() and main_path.is_file()):
            continue
        loaded = load_yaml_any(str(main_path), default_if_missing={})
        raw = loaded.get("dependencies") if isinstance(loaded, dict) else None
        names: set[str] = set()
        for entry in raw or []:
            if isinstance(entry, str):
                names.add(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("role"), str):
                names.add(entry["role"])
        deps[role_dir.name] = names
    return deps


def _consumption_kind(
    services: dict, provider_role: str, provider_provides: set[str]
) -> str | None:
    """Return how ``services`` consumes ``provider_role`` (fixed/variable/None)."""
    kinds: list[str] = []
    for key, entry in services.items():
        if not isinstance(entry, dict):
            continue
        if provider_role in _group_refs(entry):
            kinds.append("variable")
        elif key in provider_provides:
            kinds.append(_flag_kind(entry) or "fixed")
    if not kinds:
        return None
    return "fixed" if all(k == "fixed" for k in kinds) else "variable"


def _edge(src: str, dst: str, kind: str) -> str:
    if kind == "variable":
        return f'    {src} -. "0..1" .-> {dst}'
    return f'    {src} -- "1:1" --> {dst}'


def _merge_edges(edges: list[tuple[str, str, str]]) -> dict[tuple[str, str], str]:
    """Collapse duplicate ``(src, dst)`` edges; a variable edge wins over fixed."""
    merged: dict[tuple[str, str], str] = {}
    for src, dst, kind in edges:
        pair = (src, dst)
        if pair not in merged or kind == "variable":
            merged[pair] = kind
    return merged


@functools.lru_cache(maxsize=1)
def _mode_markers(roles_root_str: str) -> dict[str, str]:
    """Map each role to its deploy-mode emoji marker via the shared resolver."""
    roles_root = Path(roles_root_str)
    return {
        name: "".join(
            to_emoji(mode)
            for mode, enabled in role_deploy_modes(roles_root / name, name).items()
            if enabled
        )
        for name in _roles_meta(roles_root_str)
    }


def _role_label(name: str, markers: dict[str, str]) -> str:
    marker = markers.get(name, "")
    return f"{name} {marker}" if marker else name


def _service_stopped(entry: dict) -> bool:
    """True for a service explicitly turned off: ``enabled`` and ``shared``
    both literally ``false``."""
    return entry.get("enabled") is False and entry.get("shared") is False


def derive_cosmos_mermaid(role_dir: Path, role_name: str) -> str:
    """Return a mermaid ``flowchart`` source (no ``` fences) for the role."""
    role_dir = Path(role_dir)
    meta = _roles_meta(str(role_dir.parent))
    services = meta.get(role_name)
    if services is None:
        services_path = role_dir / ROLE_FILE_META_SERVICES
        loaded = (
            load_yaml_any(str(services_path), default_if_missing={})
            if services_path.is_file()
            else {}
        )
        services = loaded if isinstance(loaded, dict) else {}

    provides_map = {name: _provides_of(svc) for name, svc in meta.items()}
    my_provides = _provides_of(services)
    ansible_deps = _roles_ansible_deps(str(role_dir.parent))

    dep_edges: list[tuple[str, str, str]] = []
    dep_roles: set[str] = set()
    for key, entry in services.items():
        if not isinstance(entry, dict):
            continue
        for ref in _group_refs(entry):
            if ref != role_name and ref in meta:
                dep_roles.add(ref)
                dep_edges.append((ref, key, "variable"))
        for provider, provs in provides_map.items():
            if provider != role_name and key in provs:
                dep_roles.add(provider)
                dep_edges.append((provider, key, _flag_kind(entry) or "fixed"))

    gear_deps = {
        dep
        for dep in ansible_deps.get(role_name, set())
        if dep != role_name and dep in meta
    }
    dep_roles |= gear_deps

    providing_services = [
        key
        for key, entry in services.items()
        if isinstance(entry, dict) and isinstance(entry.get("provides"), str)
    ]
    anchor = providing_services or (list(services)[:1] if services else [role_name])
    dpt_kind: dict[str, str] = {}
    gear_dependents: set[str] = set()
    for other, other_services in meta.items():
        if other == role_name:
            continue
        kind = _consumption_kind(other_services, role_name, my_provides)
        if role_name in ansible_deps.get(other, set()):
            gear_dependents.add(other)
            kind = kind or "fixed"
        if kind is not None:
            dpt_kind[other] = kind

    markers = _mode_markers(str(role_dir.parent))
    dependents = sorted(dpt_kind)
    shown = dependents[:_DEPENDENTS_CAP]
    overflow = len(dependents) - len(shown)

    gear = to_emoji("role_dependency")

    lines = ["flowchart LR"]
    if dep_roles:
        lines.append("    subgraph deps [Dependencies]")
        lines.extend(
            f'        dep_{_node_id(r)}["{_role_label(r, markers)}'
            f'{f" {gear}" if r in gear_deps else ""}"]'
            for r in sorted(dep_roles)
        )
        lines.append("    end")

    lines.append(f"    subgraph role [{_role_label(role_name, markers)}]")
    if services:
        for key, entry in services.items():
            stopped = isinstance(entry, dict) and _service_stopped(entry)
            label = f"{key} {to_emoji('disabled')}" if stopped else key
            lines.append(f'        svc_{_node_id(key)}["{label}"]')
    else:
        lines.append(f'        svc_{_node_id(role_name)}["{role_name}"]')
    lines.append("    end")

    if dependents:
        lines.append("    subgraph dependents [Dependents]")
        lines.extend(
            f'        dpt_{_node_id(r)}["{_role_label(r, markers)}'
            f'{f" {gear}" if r in gear_dependents else ""}"]'
            for r in shown
        )
        if overflow:
            lines.append('        dpt_more["..."]')
        lines.append("    end")

    gear_edge_list = [
        (f"dep_{_node_id(r)}", f"svc_{_node_id(s)}", "fixed")
        for r in gear_deps
        for s in anchor[:1]
    ]
    dep_pairs = _merge_edges(
        [(f"dep_{_node_id(r)}", f"svc_{_node_id(k)}", kind) for r, k, kind in dep_edges]
        + gear_edge_list
    )
    dpt_edge_list = [
        (f"svc_{_node_id(s)}", f"dpt_{_node_id(o)}", dpt_kind[o])
        for o in shown
        for s in anchor
    ]
    if overflow:
        dpt_edge_list.extend((f"svc_{_node_id(s)}", "dpt_more", "fixed") for s in anchor)
    dpt_pairs = _merge_edges(dpt_edge_list)
    for (src, dst), kind in sorted(dep_pairs.items()):
        lines.append(_edge(src, dst, kind))
    for (src, dst), kind in sorted(dpt_pairs.items()):
        lines.append(_edge(src, dst, kind))
    return "\n".join(lines)
