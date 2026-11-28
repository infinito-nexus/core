from __future__ import annotations

import ipaddress
import re

from ansible.errors import AnsibleFilterError

CONTROLLER = "controller"
VERSION = re.compile(r"[0-9A-Za-z.+~:-]+")


def _address(hostvars: dict, host: str) -> str:
    facts = hostvars.get(host) or {}
    if facts.get("ansible_connection") == "local":
        return CONTROLLER
    name = str(facts.get("ansible_host", host)).strip().rstrip(".").casefold()
    if name == "localhost":
        return CONTROLLER
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return name
    return CONTROLLER if address.is_loopback else address.compressed


def proxmox_cohosted(
    peers: list[str],
    inventory_hostname: str,
    groups: dict,
    hostvars: dict,
) -> list[str]:
    """Return the peer roles that run on the same machine as this host: in its
    own groups or on another inventory host with the same address.

    Args:
        peers: the roles that must not share the machine.
        inventory_hostname: this host's inventory name.
        groups: the inventory ``groups`` mapping.
        hostvars: the inventory ``hostvars`` mapping.
    """
    own = _address(hostvars, inventory_hostname)
    return [
        peer
        for peer in peers
        if any(_address(hostvars, host) == own for host in groups.get(peer) or [])
    ]


def proxmox_package_pins(packages: dict) -> str:
    """Return the apt ``name=version`` list of the Proxmox VE packages; an
    unpinned package keeps its trailing ``=`` so the image build refuses it,
    and a version outside the Debian version alphabet is refused here.

    Args:
        packages: package name to pinned version.
    """
    bad = {
        name: version
        for name, version in packages.items()
        if version and not VERSION.fullmatch(str(version))
    }
    if bad:
        raise AnsibleFilterError(
            f"services.proxmox.ve.packages holds versions outside [0-9A-Za-z.+~:-]: {bad}"
        )
    return " ".join(f"{name}={packages[name] or ''}" for name in sorted(packages))


class FilterModule:
    def filters(self):
        return {
            "proxmox_cohosted": proxmox_cohosted,
            "proxmox_package_pins": proxmox_package_pins,
        }
