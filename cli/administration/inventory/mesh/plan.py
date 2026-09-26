"""Resolve a spec against an inventory into a complete mesh.

Planning is a pure function of the inventory, the spec and whatever public keys
already exist. It touches no file, so the whole correctness argument -- every
member addressed, every key paired, rotation honoured -- is unit-testable
without a deploy.
"""

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
    """The hub and the spokes ``spec`` selects out of ``groups``.

    ``controller`` joins as an ordinary spoke. It is named rather than resolved
    from a group because the Ansible controller is not a swarm member and has
    no role group of its own -- inventing one would put a non-role name into
    group_names, where every service and placement lookup would then have to
    special-case it.

    Raises when the hub group does not resolve to exactly one host: a mesh with
    no hub has no routes, and a mesh with two hubs silently splits in half.
    """
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


def plan_mesh(
    spec: MeshSpec,
    groups: dict[str, list[str]],
    existing_public_keys: dict[str, str] | None = None,
    *,
    rotate: bool = False,
    controller: str | None = None,
) -> Mesh:
    """Resolve ``spec`` into a mesh whose members are addressed and keyed.

    A member that already holds a key keeps it and carries no private half, so
    the writer leaves its stored credential untouched. Vault encryption is
    salted, so re-encrypting an unchanged secret would rewrite the file on
    every run and no deploy could ever be a no-op.

    Args:
        spec: the mesh to resolve.
        groups: inventory group name to member hostnames.
        existing_public_keys: hostname to already-issued public key.
        rotate: mint a fresh keypair for every member.
        controller: host to admit as an extra spoke, so the machine driving the
            deploy can reach the mesh it just created.
    """
    held = {} if rotate else dict(existing_public_keys or {})
    hub, spokes = members_of(spec, groups, controller)

    def member(host: str, offset: int, is_hub: bool) -> MeshMember:
        address = _address(spec.subnet, offset)
        if host in held:
            return MeshMember(
                host=host,
                address=address,
                private_key=None,
                public_key=held[host],
                is_hub=is_hub,
            )
        private_key = generate_private_key()
        return MeshMember(
            host=host,
            address=address,
            private_key=private_key,
            public_key=public_key_of(private_key),
            is_hub=is_hub,
        )

    members = [member(hub, HUB_OFFSET, True)]
    members.extend(
        member(host, SPOKE_OFFSET + index, False)
        for index, host in enumerate(spokes, start=1)
    )
    return Mesh(spec=spec, members=tuple(members))
