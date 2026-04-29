"""Walk the role tree to collect occupied ports and subnets per req-009.

Used by:
  * `cli meta ports suggest`    — gap-first port allocation suggestions
  * `cli meta networks suggest` — gap-first subnet allocation suggestions
  * `tests/lint/...`            — collision/band checks

Reads only ``roles/*/meta/{services,server}.yml`` files.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from utils.cache.yaml import load_yaml_any


REPO_ROOT = Path(__file__).resolve().parents[2]
ROLES_DIR = REPO_ROOT / "roles"


def _load_yaml(path: Path):
    if not path.is_file():
        return None
    data = load_yaml_any(str(path), default_if_missing=None)
    if data in (None, {}):
        return None
    return data


def iter_role_dirs() -> Iterable[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(p for p in ROLES_DIR.iterdir() if p.is_dir())


def iter_port_assignments() -> Iterable[Tuple[str, str, str, str, int]]:
    """Yield ``(role, entity, scope, category, port)`` for every single-int port.

    `inter` is intentionally excluded — internal container ports live in
    per-container network namespaces and never collide.
    """
    for role_dir in iter_role_dirs():
        services = _load_yaml(role_dir / "meta" / "services.yml")
        if not isinstance(services, dict):
            continue
        for entity_name, entity in services.items():
            if not isinstance(entity, dict):
                continue
            ports = entity.get("ports")
            if not isinstance(ports, dict):
                continue
            for scope_name in ("local", "public"):
                scope_map = ports.get(scope_name)
                if not isinstance(scope_map, dict):
                    continue
                for category, value in scope_map.items():
                    if category == "relay":
                        continue
                    if isinstance(value, int):
                        yield (
                            role_dir.name,
                            entity_name,
                            scope_name,
                            category,
                            value,
                        )


def iter_relay_ranges() -> Iterable[Tuple[str, str, int, int]]:
    """Yield ``(role, entity, start, end)`` for every public relay range."""
    for role_dir in iter_role_dirs():
        services = _load_yaml(role_dir / "meta" / "services.yml")
        if not isinstance(services, dict):
            continue
        for entity_name, entity in services.items():
            if not isinstance(entity, dict):
                continue
            ports = entity.get("ports")
            if not isinstance(ports, dict):
                continue
            public = ports.get("public")
            if not isinstance(public, dict):
                continue
            relay = public.get("relay")
            if not isinstance(relay, dict):
                continue
            start = relay.get("start")
            end = relay.get("end")
            if isinstance(start, int) and isinstance(end, int):
                yield (role_dir.name, entity_name, start, end)


def iter_subnets() -> Iterable[Tuple[str, ipaddress.IPv4Network]]:
    """Yield ``(role, subnet)`` for every role that declares a local subnet."""
    for role_dir in iter_role_dirs():
        server = _load_yaml(role_dir / "meta" / "server.yml")
        if not isinstance(server, dict):
            continue
        networks = server.get("networks")
        if not isinstance(networks, dict):
            continue
        local = networks.get("local")
        if not isinstance(local, dict):
            continue
        subnet_str = local.get("subnet")
        if not isinstance(subnet_str, str):
            continue
        try:
            yield role_dir.name, ipaddress.IPv4Network(subnet_str.strip())
        except (ipaddress.AddressValueError, ValueError):
            continue


def occupied_ports_for(scope: str, category: str) -> List[int]:
    """Return the sorted, de-duplicated list of host-bound ports in use for
    ``<scope>.<category>``.
    """
    seen: set[int] = set()
    for _role, _entity, scope_name, cat, port in iter_port_assignments():
        if scope_name == scope and cat == category:
            seen.add(port)
    return sorted(seen)


def occupied_relay_ranges() -> List[Tuple[int, int]]:
    """Return the sorted list of ``(start, end)`` relay ranges in use."""
    return sorted({(s, e) for _r, _e, s, e in iter_relay_ranges()})


def occupied_subnets(prefix_length: int) -> List[ipaddress.IPv4Network]:
    """Return all currently occupied subnets at the requested prefix length."""
    return sorted(
        {net for _role, net in iter_subnets() if net.prefixlen == prefix_length},
        key=lambda n: int(n.network_address),
    )


def host_bound_port_set() -> Dict[int, List[Tuple[str, str, str, str]]]:
    """Build the flat host-bound port map per req-009 lint rule.

    Returns ``{port: [(role, entity, scope, category), ...]}``. Single-int
    `local`/`public` categories AND every integer in each relay span are
    included; ``inter`` is skipped.
    """
    out: Dict[int, List[Tuple[str, str, str, str]]] = {}
    for role, entity, scope, category, port in iter_port_assignments():
        out.setdefault(port, []).append((role, entity, scope, category))
    for role, entity, start, end in iter_relay_ranges():
        for port in range(start, end + 1):
            out.setdefault(port, []).append((role, entity, "public", "relay"))
    return out
