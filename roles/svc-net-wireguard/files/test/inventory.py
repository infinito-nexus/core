"""Write the inventory of the svc-net-wireguard CLI test.

Usage:
  python inventory.py <layout> <work_dir> <mesh_role> <member>=<host>...

Args:
  layout: YAML file declaring the meshes and which member joins which; an
    optional `hub` names the member every host names as hub, an optional
    `roaming` lists the members marked roaming.
  work_dir: directory that receives devices.yml and host_vars/.
  mesh_role: role whose networks.meshes puts each host into its meshes.
  member=host: the container that plays each member of the layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from utils.cache.yaml import dump_yaml, load_yaml

APPLICATION_ID = "svc-net-wireguard"


def host_vars(
    host: str,
    meshes: list[dict],
    joined: list[str],
    mesh_role: str,
    hub: str,
    roaming: bool,
) -> dict:
    """The host_vars of one test host.

    Args:
        host: container name, which is also the inventory hostname.
        meshes: every mesh the layout declares.
        joined: the meshes this host joins.
        mesh_role: role whose networks.meshes carries the membership.
        hub: the host named as hub, or "" for none.
        roaming: whether this host is marked roaming.

    Returns:
        The host_vars mapping for that host.
    """
    own: dict = {"meshes": meshes}
    if hub:
        own["hub"] = hub
    if roaming:
        own["roaming"] = True
    return {
        "ansible_connection": "docker",
        "ansible_host": host,
        "ansible_user": "root",
        "ansible_python_interpreter": "/usr/bin/python3",
        "applications": {
            APPLICATION_ID: {"networks": own},
            mesh_role: {"networks": {"meshes": joined}},
        },
    }


def devices(hosts: list[str], mesh_role: str) -> dict:
    """The inventory putting every test host into both groups.

    Args:
        hosts: container names of the test hosts.
        mesh_role: role whose group the hosts join next to svc-net-wireguard.

    Returns:
        The devices.yml mapping.
    """
    return {
        "all": {
            "children": {
                group: {"hosts": {host: {} for host in hosts}}
                for group in (APPLICATION_ID, mesh_role)
            }
        }
    }


def main(argv: list[str]) -> int:
    layout_path, work_dir, mesh_role, *pairs = argv
    layout = load_yaml(layout_path)
    hosts = dict(pair.split("=", 1) for pair in pairs)
    hub = hosts[layout["hub"]] if "hub" in layout else ""
    roaming = set(layout["roaming"]) if "roaming" in layout else set()
    work = Path(work_dir)
    for member, host in hosts.items():
        dump_yaml(
            work / "host_vars" / f"{host}.yml",
            host_vars(
                host,
                layout["meshes"],
                layout["members"][member],
                mesh_role,
                hub,
                member in roaming,
            ),
        )
    dump_yaml(work / "devices.yml", devices(list(hosts.values()), mesh_role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
