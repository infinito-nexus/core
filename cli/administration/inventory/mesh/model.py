"""The shapes a mesh is described and resolved in.

A spec is what an operator declares. A mesh is what a spec resolves to once the
inventory has been read: every member named, addressed and keyed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MeshSpec:
    """One declared hub-and-spoke network.

    Args:
        name: identifier of the mesh, used as the interface and key prefix.
        hub_group: inventory group whose single member routes for the mesh.
        spoke_groups: inventory groups whose members peer with the hub.
        spoke_group_prefixes: group-name prefixes whose members peer with the
            hub, so a family such as ``svc-bkp-`` admits a new member without
            this declaration changing.
        subnet: the mesh address range, as ``a.b.c.0/24``.
        listen_port: UDP port the hub listens on.
        routed_range: the range a spoke routes through the hub. Wider than
            ``subnet`` whenever a spoke must reach a plane it is not a member
            of, which is the entire point of the hub being in both.
    """

    name: str
    hub_group: str
    spoke_groups: tuple[str, ...]
    subnet: str
    listen_port: int
    spoke_group_prefixes: tuple[str, ...] = ()
    routed_range: str = ""


@dataclass(frozen=True)
class MeshMember:
    """One host's place in a resolved mesh.

    Args:
        host: inventory hostname.
        address: the member's address inside the mesh subnet.
        private_key: the member's own secret half, or None when the member
            already holds one that must not be rewritten.
        public_key: the half its peers receive.
        is_hub: whether this member routes for the others.
    """

    host: str
    address: str
    private_key: str | None
    public_key: str
    is_hub: bool


@dataclass(frozen=True)
class Mesh:
    """A spec resolved against an inventory.

    Args:
        spec: the declaration this mesh was resolved from.
        members: every host in the mesh, hub first.
    """

    spec: MeshSpec
    members: tuple[MeshMember, ...] = field(default_factory=tuple)

    @property
    def hub(self) -> MeshMember:
        for member in self.members:
            if member.is_hub:
                return member
        raise ValueError(f"mesh '{self.spec.name}' resolved without a hub")

    @property
    def spokes(self) -> tuple[MeshMember, ...]:
        return tuple(m for m in self.members if not m.is_hub)

    def peers_of(self, host: str) -> tuple[MeshMember, ...]:
        """The members ``host`` is configured to reach.

        A spoke reaches only the hub. The hub reaches every spoke. Spoke to
        spoke traffic exists, but it is routed by the hub rather than peered,
        so it never appears here.
        """
        member = self.member(host)
        if member is None:
            return ()
        if member.is_hub:
            return self.spokes
        return (self.hub,)

    def member(self, host: str) -> MeshMember | None:
        for candidate in self.members:
            if candidate.host == host:
                return candidate
        return None
