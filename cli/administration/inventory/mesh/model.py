from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MeshSpec:
    """One declared mesh.

    Args:
        name: identifier of the mesh, used as the interface name.
        subnet: the mesh address range, as ``a.b.c.0/24``.
        listen_port: UDP port the hub, or every member of a full mesh,
            listens on.
        routed_range: the range a spoke routes through the hub.
    """

    name: str
    subnet: str
    listen_port: int
    routed_range: str = ""


@dataclass(frozen=True)
class Topology:
    """Who an inventory puts into each mesh.

    Args:
        hub: the host that routes for every mesh, or None for full meshes.
        spokes: mesh name to the hosts that joined it, never the hub.
        roaming: the spokes the hub neither dials nor waits for.
    """

    hub: str | None
    spokes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    roaming: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class MeshMember:
    """One host's place in a resolved mesh.

    Args:
        host: inventory hostname.
        address: the member's address inside the mesh subnet.
        endpoint: the underlay address its peers dial.
        private_key: the member's own secret half, or None when the member
            already holds one.
        public_key: the half its peers receive.
        is_hub: whether this member routes for the others.
        roaming: whether this spoke has no endpoint the hub could dial.
    """

    host: str
    address: str
    private_key: str | None
    public_key: str
    is_hub: bool
    endpoint: str = ""
    roaming: bool = False


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

    @property
    def is_full(self) -> bool:
        return not any(member.is_hub for member in self.members)

    def peers_of(self, host: str) -> tuple[MeshMember, ...]:
        member = self.member(host)
        if member is None:
            return ()
        if member.is_hub:
            return self.spokes
        if self.is_full:
            return tuple(m for m in self.members if m.host != host)
        return (self.hub,)

    def member(self, host: str) -> MeshMember | None:
        for candidate in self.members:
            if candidate.host == host:
                return candidate
        return None
