"""Read group membership and mesh declarations.

Group membership is collected across every inventory file it is spread over.
The swarm lab keeps the backup host in a sibling ``backup.yml`` rather than in
the cluster inventory, so a mesh that spans both planes is only complete when
both files have been read.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml_any

from .model import MeshSpec

MESHES_VAR = "WIREGUARD_MESHES"
POOL_VAR = "WIREGUARD_SUBNET_POOL"


def groups_of(inventory_files: list[Path]) -> dict[str, list[str]]:
    """The union of ``group -> hosts`` over every given inventory file."""
    groups: dict[str, list[str]] = {}
    for path in inventory_files:
        if not path.exists():
            continue
        document = load_yaml_any(str(path))
        if not isinstance(document, dict):
            continue
        _collect(document.get("all", {}), groups)
    return groups


def _collect(node: Any, groups: dict[str, list[str]]) -> None:
    if not isinstance(node, dict):
        return
    for name, child in (node.get("children") or {}).items():
        if not isinstance(child, dict):
            continue
        bucket = groups.setdefault(name, [])
        for host in child.get("hosts") or {}:
            if host not in bucket:
                bucket.append(host)
        _collect(child, groups)


def specs_of(group_vars_file: Path) -> list[MeshSpec]:
    """The mesh declarations in ``group_vars_file``."""
    document = load_yaml_any(str(group_vars_file))
    if not isinstance(document, dict):
        raise TypeError(f"{group_vars_file} does not contain a mapping")
    declared = document.get(MESHES_VAR)
    if not isinstance(declared, list) or not declared:
        raise ValueError(f"{group_vars_file} declares no {MESHES_VAR}")

    pool = _resolve_pool(document.get(POOL_VAR), group_vars_file)
    specs = [
        MeshSpec(
            name=entry["name"],
            hub_group=entry["hub_group"],
            spoke_groups=tuple(entry.get("spoke_groups", ())),
            subnet=entry["subnet"],
            listen_port=int(entry["listen_port"]),
            spoke_group_prefixes=tuple(entry.get("spoke_group_prefixes", ())),
            routed_range=entry.get("routed_range") or pool or entry["subnet"],
        )
        for entry in declared
    ]
    assert_no_subnet_overlap(specs, pool)
    return specs


_REFERENCE = re.compile(r"^\s*\{\{\s*(?P<name>[A-Z0-9_]+)\s*\}\}\s*$")


def _resolve_pool(pool: object, group_vars_file: Path) -> str | None:
    """The literal pool, following one ``{{ VAR }}`` hop into its SPOT.

    The pool is declared once under ``NETWORK_*`` beside every other range the
    platform allocates, and referenced from the mesh file. Ansible resolves
    that at play time; this runs before the play, so the reference is followed
    here rather than duplicating the value.
    """
    if not isinstance(pool, str):
        return None
    match = _REFERENCE.match(pool)
    if match is None:
        return pool
    name = match.group("name")
    for sibling in sorted(Path(group_vars_file).parent.glob("*.yml")):
        document = load_yaml_any(str(sibling), default_if_missing={})
        value = (document or {}).get(name)
        if isinstance(value, str) and not _REFERENCE.match(value):
            return value
    raise ValueError(f"{group_vars_file} references {name}, which no sibling defines")


def assert_no_subnet_overlap(specs: list[MeshSpec], pool: str | None) -> None:
    """Fail when two meshes overlap, or when one escapes the declared pool.

    Checked before a deploy rather than discovered at runtime, where an overlap
    presents as a peer that is configured, handshakes, and still cannot be
    reached.
    """
    networks = [
        (spec, ipaddress.ip_network(spec.subnet, strict=True)) for spec in specs
    ]

    if pool:
        allowed = ipaddress.ip_network(pool, strict=True)
        for spec, network in networks:
            if not network.subnet_of(allowed):
                raise ValueError(
                    f"mesh '{spec.name}' subnet {spec.subnet} falls outside "
                    f"the declared pool {pool}"
                )

    for index, (spec, network) in enumerate(networks):
        for other_spec, other in networks[index + 1 :]:
            if network.overlaps(other):
                raise ValueError(
                    f"mesh '{spec.name}' subnet {spec.subnet} overlaps "
                    f"mesh '{other_spec.name}' subnet {other_spec.subnet}"
                )

    ports = [spec.listen_port for spec in specs]
    duplicated = {port for port in ports if ports.count(port) > 1}
    if duplicated:
        raise ValueError(f"meshes share listen port(s): {sorted(duplicated)}")
