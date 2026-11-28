from __future__ import annotations

import sys
from typing import Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VARIANTS, ROLE_FILE_VARS_MAIN

PROXMOX_APP = "web-app-proxmox"
DEDICATED_FLAVOR = "container"
PROFILE = "proxmox"
INVENTORY = "proxmox.yml"
_ROLE = PROJECT_ROOT / "roles" / PROXMOX_APP
_VARIANTS = _ROLE / ROLE_FILE_META_VARIANTS


def peers() -> list[str]:
    """
    Returns:
        The roles web-app-proxmox refuses to share a machine with, read from
        ``PROXMOX_EXCLUSIVE_PEERS`` of the role's vars.
    """
    variables = load_yaml_any(str(_ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
    return list((variables or {}).get("PROXMOX_EXCLUSIVE_PEERS") or [])


def _flavor(entry: dict[str, Any] | None) -> str:
    services = (entry or {}).get("services") or {}
    return str((services.get("proxmox") or {}).get("flavor") or "")


def runs_on_proxmox_host(app_id: str, applications: dict[str, Any]) -> bool:
    """
    Args:
        app_id: the round's primary application.
        applications: the round's applications with its variant applied.

    Returns:
        Whether the round deploys the container flavor of web-app-proxmox,
        which runs alone on the dedicated Proxmox host.
    """
    return app_id == PROXMOX_APP and (
        _flavor(applications.get(app_id)) == DEDICATED_FLAVOR
    )


def profiles(app_id: str) -> list[str]:
    """
    Args:
        app_id: the application the lab is brought up for.

    Returns:
        The compose profile of the Proxmox host when a variant of the
        application deploys the container flavor, otherwise none.
    """
    if app_id != PROXMOX_APP:
        return []
    variants = load_yaml_any(str(_VARIANTS), default_if_missing=[]) or []
    return [PROFILE] if any(_flavor(v) == DEDICATED_FLAVOR for v in variants) else []


def split_off_proxmox_host(
    children: dict[str, Any], app_id: str, host: str, host_vars: dict[str, str]
) -> dict[str, Any]:
    """
    Args:
        children: the ``all.children`` map of the cluster inventory; the
            application's group is taken out of it in place.
        app_id: the application that runs alone on the Proxmox host.
        host: the Proxmox host.
        host_vars: the connection variables of a lab host.

    Returns:
        The ``all.children`` of the sibling inventory: the application on the
        Proxmox host and every peer group of the cluster on its cluster hosts,
        with no swarm group, so the host resolves to compose mode.

    Raises:
        ValueError: when a group of the cluster inventory lists the host.
    """
    children.pop(app_id, None)
    shared = sorted(
        group
        for group, body in children.items()
        if host in ((body or {}).get("hosts") or {})
    )
    if shared:
        raise ValueError(
            f"proxmox_host: {host} has to run {app_id} alone, "
            f"but the inventory also puts {', '.join(shared)} on it"
        )
    sibling: dict[str, Any] = {app_id: {"hosts": {host: dict(host_vars)}}}
    for peer in peers():
        hosts = ((children.get(peer) or {}).get("hosts")) or {}
        if hosts:
            sibling[peer] = {
                "hosts": {name: dict(v or {}) for name, v in hosts.items()}
            }
    return sibling


def main(argv: list[str]) -> int:
    """
    Args:
        argv: the application id the lab is brought up for.

    Returns:
        The exit status; the compose profiles go to stdout, one per line.
    """
    (app_id,) = argv
    for profile in profiles(app_id):
        print(profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
