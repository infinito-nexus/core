from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

APPLICATION_ID = "svc-net-wireguard"
HUB_ROLE = "svc-swarm-manager"
MESHES_KEY = "meshes"
INTERFACES_KEY = "interfaces"
HUB_KEY = "hub"
ROAMING_KEY = "roaming"


def _networks(applications: Any, role: str) -> Mapping[str, Any]:
    if not isinstance(applications, Mapping):
        return {}
    networks = (applications.get(role) or {}).get("networks") or {}
    return networks if isinstance(networks, Mapping) else {}


def _listed(applications: Any, role: str, key: str) -> list[Any]:
    value = _networks(applications, role).get(key)
    return list(value) if isinstance(value, (list, tuple)) else []


def declared_meshes(applications: Any) -> list[Mapping[str, Any]]:
    return [
        entry
        for entry in _listed(applications, APPLICATION_ID, MESHES_KEY)
        if isinstance(entry, Mapping)
    ]


def declared_hub(applications: Any) -> str:
    """The host a host's ``applications`` names as the hub, or ``""``.

    Args:
        applications: the host's ``applications`` block.
    """
    value = _networks(applications, APPLICATION_ID).get(HUB_KEY)
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise TypeError(
            f"{APPLICATION_ID}.networks.{HUB_KEY} names a host, got {value!r}"
        )
    return value


def is_roaming(applications: Any) -> bool:
    """Whether a host's ``applications`` marks it as a roaming spoke.

    Args:
        applications: the host's ``applications`` block.
    """
    value = _networks(applications, APPLICATION_ID).get(ROAMING_KEY)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeError(
            f"{APPLICATION_ID}.networks.{ROAMING_KEY} is true or false, got {value!r}"
        )
    return value


def joined_meshes(applications: Any, roles: Iterable[str]) -> dict[str, list[str]]:
    """Mesh name to the roles that put the host into it.

    Args:
        applications: the host's ``applications`` block.
        roles: the role groups the host belongs to; a name in this role's
            own ``networks.meshes`` joins too, a mapping there declares.
    """
    joined: dict[str, list[str]] = {}
    for role in roles:
        for name in _listed(applications, role, MESHES_KEY):
            if role == APPLICATION_ID and isinstance(name, Mapping):
                continue
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


def awaited_peers(
    interface: Mapping[str, Any], swarm_manager: bool
) -> list[Mapping[str, Any]]:
    """The peers a deploy waits to have handshaked with on ``interface``.

    Args:
        interface: one entry of this role's ``networks.interfaces``.
        swarm_manager: whether the host is the swarm manager, which waits for
            none of its spokes.
    """
    if not interface.get("is_hub"):
        return _peers(interface)
    if swarm_manager:
        return []
    return [peer for peer in _peers(interface) if peer.get("endpoint")]


def awaited_keys(
    meshes: Mapping[str, Mapping[str, Any]], swarm_manager: bool
) -> dict[str, list[str]]:
    """Mesh name to the public keys its interface waits for, empty ones left out.

    Args:
        meshes: mesh name to this host's interface on it.
        swarm_manager: whether the host is the swarm manager.
    """
    awaited: dict[str, list[str]] = {}
    for name, interface in sorted(meshes.items()):
        keys = [
            str(peer["public_key"]) for peer in awaited_peers(interface, swarm_manager)
        ]
        if keys:
            awaited[str(name)] = keys
    return awaited


def handshaken(latest_handshakes: str, public_keys: Iterable[str]) -> bool:
    """Whether every key in ``public_keys`` has completed a handshake.

    Args:
        latest_handshakes: the output of ``wg show <mesh> latest-handshakes``.
        public_keys: the peers that must have handshaked.
    """
    stamps: dict[str, int] = {}
    for line in latest_handshakes.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].isdigit():
            stamps[fields[0]] = int(fields[1])
    return all(key in stamps and stamps[key] > 0 for key in public_keys)


def primary_address(applications: Any, host: str) -> str:
    for entry in interfaces(applications):
        if entry.get("primary") and entry.get("host") == host:
            address = entry.get("address")
            if isinstance(address, str) and address:
                return address
    return ""
