from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

from cli.administration.inventory.provision.ruamel_io import load_document
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.mesh import (
    APPLICATION_ID,
    HUB_KEY,
    HUB_ROLE,
    MESHES_KEY,
    ROAMING_KEY,
    declared_hub,
    declared_meshes,
    is_roaming,
    joined_meshes,
)

from .model import MeshSpec, Topology

POOL_VAR = "NETWORK_MESH_POOL"


def groups_of(inventory_files: list[Path]) -> dict[str, list[str]]:
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


def host_applications(host_vars_dir: Path, host: str) -> Any:
    path = host_vars_dir / f"{host}.yml"
    if not path.is_file():
        return {}
    return load_document(path).get("applications") or {}


def _hosts(groups: dict[str, list[str]]) -> list[str]:
    return sorted({host for members in groups.values() for host in members})


def swarm_manager_of(groups: dict[str, list[str]]) -> str | None:
    hubs = sorted(dict.fromkeys(groups.get(HUB_ROLE, [])))
    if not hubs:
        return None
    if len(hubs) != 1:
        raise ValueError(
            f"hub group '{HUB_ROLE}' resolves to {len(hubs)} hosts, expected exactly 1"
        )
    return hubs[0]


def named_hub_of(groups: dict[str, list[str]], host_vars_dir: Path) -> str | None:
    """The host the inventory names in ``networks.hub``, or None.

    Args:
        groups: group to hosts over every inventory of the deploy.
        host_vars_dir: directory holding one ``<host>.yml`` per host.
    """
    hosts = _hosts(groups)
    named: dict[str, list[str]] = {}
    for host in hosts:
        hub = declared_hub(host_applications(host_vars_dir, host))
        if hub:
            named.setdefault(hub, []).append(host)
    if not named:
        return None
    if len(named) != 1:
        raise ValueError(
            f"{APPLICATION_ID}.networks.{HUB_KEY} names different hubs: "
            + "; ".join(
                f"{hub} by {', '.join(by)}" for hub, by in sorted(named.items())
            )
        )
    hub = next(iter(named))
    if hub not in hosts:
        raise ValueError(
            f"{APPLICATION_ID}.networks.{HUB_KEY} names '{hub}', which no "
            "inventory of this deploy holds"
        )
    return hub


def hub_of(groups: dict[str, list[str]], host_vars_dir: Path) -> str | None:
    """The hub of every mesh: the swarm manager, else the named hub, else None.

    Args:
        groups: group to hosts over every inventory of the deploy.
        host_vars_dir: directory holding one ``<host>.yml`` per host.
    """
    manager = swarm_manager_of(groups)
    named = named_hub_of(groups, host_vars_dir)
    if manager is not None and named is not None and named != manager:
        raise ValueError(
            f"{APPLICATION_ID}.networks.{HUB_KEY} names '{named}', but the "
            f"'{HUB_ROLE}' host '{manager}' is the hub of a swarm deployment"
        )
    return manager if manager is not None else named


def declared_specs(
    groups: dict[str, list[str]], host_vars_dir: Path, inventory_files: list[Path]
) -> list[MeshSpec]:
    """The meshes the deployment declares, in declaration order.

    Args:
        groups: group to hosts over every inventory of the deploy.
        host_vars_dir: directory holding one ``<host>.yml`` per host.
        inventory_files: the inventories of the deploy.
    """
    hub = hub_of(groups, host_vars_dir)
    if hub is not None:
        return specs_of(host_applications(host_vars_dir, hub), inventory_files)
    by_host: dict[str, list[MeshSpec]] = {}
    for host in _hosts(groups):
        applications = host_applications(host_vars_dir, host)
        if declared_meshes(applications):
            by_host[host] = specs_of(applications, inventory_files)
    if not by_host:
        raise ValueError(
            f"{APPLICATION_ID} declares no networks.{MESHES_KEY} on any host: "
            "without a hub, a deployment states its meshes in every member's "
            "host_vars"
        )
    first, specs = next(iter(by_host.items()))
    differing = sorted(host for host, other in by_host.items() if other != specs)
    if differing:
        raise ValueError(
            f"{', '.join(differing)} declare(s) other meshes than {first}: "
            "without a hub, every host that declares meshes declares the same"
        )
    return specs


def specs_of(applications: Any, inventory_files: list[Path]) -> list[MeshSpec]:
    """The meshes declared in *applications*, in declaration order.

    Args:
        applications: the declaring host's ``applications`` block.
        inventory_files: the inventories of the deploy.
    """
    declared = declared_meshes(applications)
    if not declared:
        raise ValueError(
            f"{APPLICATION_ID} declares no networks.{MESHES_KEY}: a deployment "
            "states its meshes in the hub's host_vars"
        )
    pool = pool_of(inventory_files)
    specs = [
        MeshSpec(
            name=str(entry["name"]),
            subnet=str(entry["subnet"]),
            listen_port=int(entry["listen_port"]),
            routed_range=str(entry.get("routed_range") or pool),
        )
        for entry in declared
    ]
    names = [spec.name for spec in specs]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValueError(f"meshes declared more than once: {duplicated}")
    assert_no_subnet_overlap(specs, pool)
    return specs


def topology_of(
    groups: dict[str, list[str]], host_vars_dir: Path, specs: list[MeshSpec]
) -> Topology:
    hub = hub_of(groups, host_vars_dir)
    spokes: dict[str, list[str]] = {spec.name: [] for spec in specs}
    roaming: set[str] = set()
    for host in _hosts(groups):
        applications = host_applications(host_vars_dir, host)
        if is_roaming(applications):
            if hub is None:
                raise ValueError(
                    f"{host} is marked {ROAMING_KEY}, which needs a hub: name one "
                    f"in {APPLICATION_ID}.networks.{HUB_KEY}"
                )
            if host == hub:
                raise ValueError(
                    f"{host} is the hub every spoke dials, so it cannot be "
                    f"marked {ROAMING_KEY}"
                )
            roaming.add(host)
        roles = [group for group, members in groups.items() if host in members]
        joined = joined_meshes(applications, roles)
        for name, by in sorted(joined.items()):
            if name not in spokes:
                raise ValueError(
                    f"{host}: {', '.join(by)} join(s) mesh '{name}', which "
                    f"{APPLICATION_ID} does not declare"
                )
            if host != hub:
                spokes[name].append(host)
    return Topology(
        hub=hub,
        spokes={name: tuple(h) for name, h in spokes.items()},
        roaming=frozenset(roaming),
    )


_REFERENCE = re.compile(r"^\s*\{\{\s*(?P<name>[A-Z0-9_]+)\s*\}\}\s*$")


def _literal_of(name: str, directories: list[Path]) -> str | None:
    for directory in directories:
        for path in sorted(directory.glob("*.yml")):
            document = load_yaml_any(str(path), default_if_missing={})
            value = (document or {}).get(name)
            if isinstance(value, str) and not _REFERENCE.match(value):
                return value
    return None


def pool_of(inventory_files: list[Path]) -> str:
    directories: list[Path] = []
    for path in inventory_files:
        group_vars = Path(path).parent / "group_vars"
        directories += [group_vars, group_vars / "all"]
    directories.append(PROJECT_ROOT / "group_vars" / "all")
    pool = _literal_of(POOL_VAR, list(dict.fromkeys(directories)))
    if pool is None:
        raise ValueError(f"{POOL_VAR} is defined nowhere the deploy reads it from")
    return pool


def assert_no_subnet_overlap(specs: list[MeshSpec], pool: str | None) -> None:
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
