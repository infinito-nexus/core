"""Resolve a spec against an inventory into a complete mesh."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from .keys import generate_private_key, public_key_of
from .model import Mesh, MeshMember

if TYPE_CHECKING:
    from .model import MeshSpec

HUB_OFFSET = 1
SPOKE_OFFSET = 10


def members_of(
    spec: MeshSpec, groups: dict[str, list[str]], controller: str | None = None
) -> tuple[str, list[str]]:
    """The hub and the spokes ``spec`` selects out of ``groups``."""
    hubs = sorted(dict.fromkeys(groups.get(spec.hub_group, [])))
    if len(hubs) != 1:
        raise ValueError(
            f"mesh '{spec.name}': hub group '{spec.hub_group}' resolves to "
            f"{len(hubs)} hosts, expected exactly 1"
        )
    hub = hubs[0]

    selected = set(spec.spoke_groups)
    selected.update(
        name
        for name in groups
        if any(name.startswith(prefix) for prefix in spec.spoke_group_prefixes)
    )

    spokes: list[str] = []
    for group in sorted(selected):
        for host in groups.get(group, []):
            if host != hub and host not in spokes:
                spokes.append(host)
    if controller and controller != hub and controller not in spokes:
        spokes.append(controller)
    return hub, sorted(spokes)


def _address(subnet: str, offset: int) -> str:
    network = ipaddress.ip_network(subnet, strict=True)
    address = network.network_address + offset
    if address not in network:
        raise ValueError(f"offset {offset} falls outside {subnet}")
    return str(address)


def _offset_of(subnet: str, address: str) -> int | None:
    """The spoke offset ``address`` occupies in ``subnet``, or None."""
    network = ipaddress.ip_network(subnet, strict=True)
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return None
    if candidate not in network:
        return None
    offset = int(candidate) - int(network.network_address)
    return offset if offset > SPOKE_OFFSET else None


def _spoke_offsets(
    subnet: str, spokes: list[str], stored: dict[str, str]
) -> dict[str, int]:
    """Keep every spoke on the address it already holds.

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
    groups: dict[str, list[str]],
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
        groups: inventory group name to member hostnames.
        existing_public_keys: hostname to already-issued public key.
        rotate: mint a fresh keypair for every member.
        controller: host to admit as an extra spoke, so the machine driving the
            deploy can reach the mesh it just created.
        endpoints: hostname to the underlay address its peers dial. A host
            left out keeps its hostname, which is what every peer already
            resolves and routes to wherever inventory names are real names.
        addresses: hostname to the mesh address it already holds. Kept across
            a rotation too: rotation replaces identities, not addresses.
    """
    held = {} if rotate else dict(existing_public_keys or {})
    underlay = dict(endpoints or {})
    hub, spokes = members_of(spec, groups, controller)
    offsets = _spoke_offsets(spec.subnet, spokes, dict(addresses or {}))

    def member(host: str, offset: int, is_hub: bool) -> MeshMember:
        address = _address(spec.subnet, offset)
        endpoint = underlay.get(host, host)
        if host in held:
            return MeshMember(
                host=host,
                address=address,
                private_key=None,
                public_key=held[host],
                is_hub=is_hub,
                endpoint=endpoint,
            )
        private_key = generate_private_key()
        return MeshMember(
            host=host,
            address=address,
            private_key=private_key,
            public_key=public_key_of(private_key),
            is_hub=is_hub,
            endpoint=endpoint,
        )

    members = [member(hub, HUB_OFFSET, True)]
    members.extend(member(host, offsets[host], False) for host in spokes)
    return Mesh(spec=spec, members=tuple(members))
