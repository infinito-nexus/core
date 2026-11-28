"""Walk the role tree to collect occupied ports and subnets.

Used by:
  * `cli contributing network ports suggest`   gap-first port allocation suggestions
  * `cli contributing network address suggest` gap-first subnet allocation suggestions
  * `tests/lint/...`                           collision/band checks

Reads only ``roles/*/meta/{services,server}.yml`` files.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.networks import STREAM_RELAY
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


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


def iter_port_assignments() -> Iterable[tuple[str, str, str, str, int]]:
    """Yield ``(role, entity, scope, category, port)`` for every single-int port.

    `internal` is intentionally excluded — internal container ports live in
    per-container network namespaces and never collide.
    """
    for role_dir in iter_role_dirs():
        services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
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


def iter_relay_ranges() -> Iterable[tuple[str, str, int, int]]:
    """Yield ``(role, entity, start, end)`` for every public relay range."""
    for role_dir in iter_role_dirs():
        services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
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


def _subnet_at(node: object, *keys: str) -> str | None:
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) else None


def iter_subnets() -> Iterable[tuple[str, ipaddress.IPv4Network]]:
    """Yield ``(owner, subnet)`` for every subnet a role pins.

    ``owner`` is the role for its ``local.subnet`` and ``<role>:stream_relay``
    for the subnet of its stream relay network, so the allocator and the pool
    lint see both.
    """
    for role_dir in iter_role_dirs():
        networks = _load_yaml(role_dir / ROLE_FILE_META_NETWORKS)
        pinned = (
            (role_dir.name, _subnet_at(networks, "local", "subnet")),
            (
                f"{role_dir.name}:{STREAM_RELAY}",
                _subnet_at(networks, "overlay", STREAM_RELAY, "subnet"),
            ),
        )
        for owner, subnet_str in pinned:
            if subnet_str is None:
                continue
            try:
                yield owner, ipaddress.IPv4Network(subnet_str.strip())
            except (ipaddress.AddressValueError, ValueError):
                continue


def iter_outside_pool_roles() -> Iterable[str]:
    """Yield every role whose ``meta/networks.yml`` sets ``local.outside_pool``."""
    for role_dir in iter_role_dirs():
        networks = _load_yaml(role_dir / ROLE_FILE_META_NETWORKS)
        local = networks.get("local") if isinstance(networks, dict) else None
        if isinstance(local, dict) and local.get("outside_pool") is True:
            yield role_dir.name


def occupied_ports_for(scope: str, category: str) -> list[int]:
    """Return the sorted, de-duplicated list of host-bound ports in use for
    ``<scope>.<category>``.
    """
    seen: set[int] = set()
    for _role, _entity, scope_name, cat, port in iter_port_assignments():
        if scope_name == scope and cat == category:
            seen.add(port)
    return sorted(seen)


def occupied_relay_ranges() -> list[tuple[int, int]]:
    """Return the sorted list of ``(start, end)`` relay ranges in use."""
    return sorted({(s, e) for _r, _e, s, e in iter_relay_ranges()})


def occupied_subnets(prefix_length: int) -> list[ipaddress.IPv4Network]:
    """Return all currently occupied subnets at the requested prefix length."""
    return sorted(
        {net for _role, net in iter_subnets() if net.prefixlen == prefix_length},
        key=lambda n: int(n.network_address),
    )


def host_bound_port_set() -> dict[int, list[tuple[str, str, str, str]]]:
    """Build the flat host-bound port map for the lint rule.

    Returns ``{port: [(role, entity, scope, category), ...]}``. Single-int
    `local`/`public` categories AND every integer in each relay span are
    included; ``internal`` is skipped.
    """
    out: dict[int, list[tuple[str, str, str, str]]] = {}
    for role, entity, scope, category, port in iter_port_assignments():
        out.setdefault(port, []).append((role, entity, scope, category))
    for role, entity, start, end in iter_relay_ranges():
        for port in range(start, end + 1):
            out.setdefault(port, []).append((role, entity, "public", "relay"))
    return out
