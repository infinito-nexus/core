from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from .keys import generate_private_key, public_key_of
from .model import Mesh, MeshMember

if TYPE_CHECKING:
    from .model import MeshSpec, Topology

HUB_OFFSET = 1
SPOKE_OFFSET = 10


def members_of(
    spec: MeshSpec, topology: Topology, controller: str | None = None
) -> tuple[str | None, list[str]]:
    spokes = [
        host
        for host in dict.fromkeys(topology.spokes.get(spec.name, ()))
        if host != topology.hub
    ]
    if controller and controller != topology.hub and controller not in spokes:
        spokes.append(controller)
    return topology.hub, sorted(spokes)


def primary_meshes(
    specs: list[MeshSpec],
    topology: Topology,
    controller: str | None = None,
    controller_mesh: str | None = None,
) -> dict[str, str]:
    """The first declared mesh each host belongs to.

    Args:
        specs: every declared mesh, in declaration order.
        topology: who the inventory puts into each mesh.
        controller: host admitted as an extra spoke of ``controller_mesh``.
        controller_mesh: the mesh ``controller`` joins.

    Returns:
        hostname to the name of its primary mesh.
    """
    primary: dict[str, str] = {}
    for spec in specs:
        hub, spokes = members_of(
            spec, topology, controller if spec.name == controller_mesh else None
        )
        for host in [hub, *spokes] if hub else spokes:
            primary.setdefault(host, spec.name)
    return primary


def _address(subnet: str, offset: int) -> str:
    network = ipaddress.ip_network(subnet, strict=True)
    address = network.network_address + offset
    if address not in network:
        raise ValueError(f"offset {offset} falls outside {subnet}")
    return str(address)


def _offset_of(subnet: str, address: str) -> int | None:
    network = ipaddress.ip_network(subnet, strict=True)
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return None
    if candidate not in network or candidate == network.broadcast_address:
        return None
    offset = int(candidate) - int(network.network_address)
    return offset if offset > HUB_OFFSET else None


def _spoke_offsets(
    subnet: str, spokes: list[str], stored: dict[str, str]
) -> dict[str, int]:
    """Hostname to its offset, keeping every address a spoke already holds.

    Args:
        subnet: the mesh subnet offsets are taken in.
        spokes: every spoke of the mesh, in the order they were resolved.
        stored: hostname to the address it already holds on this mesh.
    """
    taken = {HUB_OFFSET}
    offsets: dict[str, int] = {}
    for host in spokes:
        offset = _offset_of(subnet, stored.get(host, ""))
        if offset is None or offset in taken:
            continue
        offsets[host] = offset
        taken.add(offset)

    cursor = SPOKE_OFFSET + 1
    for host in spokes:
        if host in offsets:
            continue
        while cursor in taken:
            cursor += 1
        offsets[host] = cursor
        taken.add(cursor)
    return offsets


def plan_mesh(
    spec: MeshSpec,
    topology: Topology,
    existing_public_keys: dict[str, str] | None = None,
    *,
    rotate: bool = False,
    controller: str | None = None,
    endpoints: dict[str, str] | None = None,
    addresses: dict[str, str] | None = None,
) -> Mesh:
    """Resolve ``spec`` into a mesh whose members are addressed and keyed.

    Args:
        spec: the mesh to resolve.
        topology: who the inventory puts into each mesh.
        existing_public_keys: hostname to already-issued public key.
        rotate: mint a fresh keypair for every member.
        controller: host to admit as an extra spoke.
        endpoints: hostname to the underlay address its peers dial; a host
            left out is dialled by its hostname, a roaming spoke takes none.
        addresses: hostname to the mesh address it already holds, kept across
            a rotation.
    """
    held = {} if rotate else dict(existing_public_keys or {})
    underlay = dict(endpoints or {})
    hub, spokes = members_of(spec, topology, controller)
    roaming = {host for host in spokes if host in topology.roaming}
    dialled_roamers = sorted(roaming & set(underlay))
    if dialled_roamers:
        raise ValueError(
            f"{', '.join(dialled_roamers)} roam(s), so no peer dials them: "
            "drop their --endpoint"
        )
    offsets = _spoke_offsets(spec.subnet, spokes, dict(addresses or {}))

    def member(host: str, offset: int, is_hub: bool) -> MeshMember:
        address = _address(spec.subnet, offset)
        endpoint = "" if host in roaming else underlay.get(host, host)
        if host in held:
            return MeshMember(
                host=host,
                address=address,
                private_key=None,
                public_key=held[host],
                is_hub=is_hub,
                endpoint=endpoint,
                roaming=host in roaming,
            )
        private_key = generate_private_key()
        return MeshMember(
            host=host,
            address=address,
            private_key=private_key,
            public_key=public_key_of(private_key),
            is_hub=is_hub,
            endpoint=endpoint,
            roaming=host in roaming,
        )

    members = [member(hub, HUB_OFFSET, True)] if hub else []
    members.extend(member(host, offsets[host], False) for host in spokes)
    return Mesh(spec=spec, members=tuple(members))
