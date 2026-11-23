from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

from ansible.errors import AnsibleFilterError

if TYPE_CHECKING:
    from collections.abc import Iterator

WORKSPACE_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
IFNAME_MAX = 15
MARKER = "user.infinito.workspace"


def incus_workspace_bridge(workspace: str, prefix: str) -> str:
    """Args:
        workspace: the workspace id, a lowercase UUID.
        prefix: ``services.incus.workspaces.bridge_prefix``.

    Returns:
        The name of the workspace's bridge, at most 15 characters.
    """
    if not WORKSPACE_ID.fullmatch(str(workspace)):
        raise AnsibleFilterError(f"workspace id {workspace!r} is no lowercase UUID")
    return f"{prefix}{workspace.replace('-', '')}"[:IFNAME_MAX]


def _slices(subnet: str, prefix: int) -> Iterator[ipaddress._BaseNetwork]:
    network = ipaddress.ip_network(str(subnet), strict=True)
    if int(prefix) < network.prefixlen or int(prefix) > network.max_prefixlen - 2:
        raise AnsibleFilterError(
            f"a /{prefix} slice does not fit {subnet} with a gateway and an instance"
        )
    return network.subnets(new_prefix=int(prefix))


def _bridge_config(workspace: str, ipv4: str, ipv6: str) -> dict[str, str]:
    return {
        "ipv4.address": ipv4,
        "ipv4.nat": "false",
        "ipv4.dhcp": "true",
        "ipv6.address": ipv6,
        "ipv6.nat": "false",
        "ipv6.dhcp.stateful": "true",
        MARKER: workspace,
    }


def _bridge(name: str, config: dict[str, str], current: dict | None) -> dict:
    return {
        "name": name,
        "config": config,
        "settings": [f"{key}={value}" for key, value in config.items()],
        "exists": current is not None,
        "converged": current is not None
        and all(current.get(key) == value for key, value in config.items()),
    }


def incus_workspace_bridges(workspace: str, networks: list) -> list[str]:
    """Args:
        workspace: the workspace id.
        networks: ``incus query /1.0/networks?recursion=1`` of the host.

    Returns:
        The names of the bridges that serve the workspace.
    """
    return [
        network["name"]
        for network in networks or []
        if (network.get("config") or {}).get(MARKER) == workspace
    ]


def incus_workspace_network(workspace: str, workspaces: dict, networks: list) -> dict:
    """Args:
        workspace: the workspace id, a lowercase UUID.
        workspaces: ``services.incus.workspaces``.
        networks: ``incus query /1.0/networks?recursion=1`` of the host.

    Returns:
        ``{"name", "config", "settings", "exists", "converged"}`` of the
        workspace's bridge: the slice it already holds, else the lowest free
        slice pair of both routed subnets.
    """
    subnet = workspaces["subnet"]
    if not subnet.get("ipv4") or not subnet.get("ipv6"):
        raise AnsibleFilterError(
            "services.incus.workspaces.subnet.ipv4 and .ipv6 must both name the routed subnet"
        )
    name = incus_workspace_bridge(workspace, workspaces["bridge_prefix"])
    taken: list[ipaddress._BaseNetwork] = []
    for network in networks or []:
        config = network.get("config") or {}
        owner = config.get(MARKER)
        if owner == workspace:
            return _bridge(
                network["name"],
                _bridge_config(
                    workspace, config["ipv4.address"], config["ipv6.address"]
                ),
                config,
            )
        if network.get("name") == name:
            raise AnsibleFilterError(
                f"bridge {name} exists and serves {owner or 'no workspace'}, not {workspace}"
            )
        for family in ("ipv4.address", "ipv6.address"):
            address = config.get(family, "")
            if address and address not in ("none", "auto"):
                taken.append(ipaddress.ip_interface(address).network)
    pairs = zip(
        _slices(subnet["ipv4"], workspaces["slice"]["ipv4"]),
        _slices(subnet["ipv6"], workspaces["slice"]["ipv6"]),
        strict=False,
    )
    for ipv4, ipv6 in pairs:
        if not any(ipv4.overlaps(other) or ipv6.overlaps(other) for other in taken):
            return _bridge(
                name,
                _bridge_config(
                    workspace,
                    f"{ipv4.network_address + 1}/{ipv4.prefixlen}",
                    f"{ipv6.network_address + 1}/{ipv6.prefixlen}",
                ),
                None,
            )
    raise AnsibleFilterError(
        f"no free /{workspaces['slice']['ipv4']} and /{workspaces['slice']['ipv6']} slice pair is left in the routed subnets"
    )


def incus_workspace_project(
    bridge: str, workspaces: dict, restrictions: dict
) -> dict[str, str]:
    """Args:
        bridge: the workspace's bridge.
        workspaces: ``services.incus.workspaces``.
        restrictions: the restrictions of the agents project.

    Returns:
        The project config: the agents restrictions, the own bridge, virtual
        machines only and the plan's limits.
    """
    limits = workspaces["limits"]
    return {
        **{key: str(value) for key, value in restrictions.items()},
        "restricted.networks.access": bridge,
        "limits.containers": "0",
        "limits.instances": str(limits["instances"]),
        "limits.cpu": str(limits["cpu"]),
        "limits.memory": str(limits["memory"]),
        "limits.disk": str(limits["disk"]),
    }


def incus_workspace_profile(
    workspace: str, bridge: str, pool: str, workspaces: dict
) -> dict:
    """Args:
        workspace: the workspace id.
        bridge: the workspace's bridge.
        pool: the storage pool of the instances.
        workspaces: ``services.incus.workspaces``.

    Returns:
        The default profile of ``ws-<id>``: instance sizes the project limits
        count, a root disk in the pool and a NIC that sends from its own
        addresses only.
    """
    instance = workspaces["instance"]
    return {
        "description": f"ws-{workspace}",
        "config": {
            "limits.cpu": str(instance["cpu"]),
            "limits.memory": str(instance["memory"]),
        },
        "devices": {
            "root": {
                "type": "disk",
                "path": "/",
                "pool": pool,
                "size": str(instance["disk"]),
            },
            "eth0": {
                "type": "nic",
                "name": "eth0",
                "network": bridge,
                "security.mac_filtering": "true",
                "security.ipv4_filtering": "true",
                "security.ipv6_filtering": "true",
            },
        },
    }


class FilterModule:
    def filters(self):
        return {
            "incus_workspace_bridges": incus_workspace_bridges,
            "incus_workspace_network": incus_workspace_network,
            "incus_workspace_project": incus_workspace_project,
            "incus_workspace_profile": incus_workspace_profile,
        }
