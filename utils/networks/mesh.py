from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

APPLICATION_ID = "svc-net-wireguard"
HUB_ROLE = "svc-swarm-manager"
MESHES_KEY = "meshes"
INTERFACES_KEY = "interfaces"


def _listed(applications: Any, role: str, key: str) -> list[Any]:
    if not isinstance(applications, Mapping):
        return []
    networks = (applications.get(role) or {}).get("networks") or {}
    value = networks.get(key) if isinstance(networks, Mapping) else None
    return list(value) if isinstance(value, (list, tuple)) else []


def declared_meshes(applications: Any) -> list[Mapping[str, Any]]:
    return [
        entry
        for entry in _listed(applications, APPLICATION_ID, MESHES_KEY)
        if isinstance(entry, Mapping)
    ]


def joined_meshes(applications: Any, roles: Iterable[str]) -> dict[str, list[str]]:
    """Mesh name to the roles that put the host into it.

    Args:
        applications: the host's ``applications`` block.
        roles: the role groups the host belongs to.
    """
    joined: dict[str, list[str]] = {}
    for role in roles:
        if role == APPLICATION_ID:
            continue
        for name in _listed(applications, role, MESHES_KEY):
            joined.setdefault(str(name), []).append(role)
    return joined


def interfaces(applications: Any) -> list[Mapping[str, Any]]:
    return [
        entry
        for entry in _listed(applications, APPLICATION_ID, INTERFACES_KEY)
        if isinstance(entry, Mapping)
    ]


def owned_interface(
    applications: Any, host: str, mesh: str
) -> Mapping[str, Any] | None:
    for entry in interfaces(applications):
        if entry.get("name") == mesh and entry.get("host") == host:
            return entry
    return None


def address_on(applications: Any, host: str, mesh: str) -> str:
    entry = owned_interface(applications, host, mesh) or {}
    address = entry.get("address")
    return address if isinstance(address, str) else ""


def _peers(interface: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    listed = interface.get("peers")
    if not isinstance(listed, (list, tuple)):
        return []
    return [peer for peer in listed if isinstance(peer, Mapping)]


def is_full(interface: Mapping[str, Any]) -> bool:
    return not interface.get("is_hub") and not any(
        peer.get("is_hub") for peer in _peers(interface)
    )


def listens(interface: Mapping[str, Any]) -> bool:
    return bool(interface.get("is_hub")) or is_full(interface)


def dialled_peers(interface: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    peers = _peers(interface)
    if is_full(interface):
        return peers
    return [peer for peer in peers if peer.get("is_hub")]


def primary_address(applications: Any, host: str) -> str:
    for entry in interfaces(applications):
        if entry.get("primary") and entry.get("host") == host:
            address = entry.get("address")
            if isinstance(address, str) and address:
                return address
    return ""
