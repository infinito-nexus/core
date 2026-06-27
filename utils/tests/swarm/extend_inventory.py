#!/usr/bin/env python3
"""Extend the provisioned test inventory with host-topology placements
plus the dep-walked ``default_placement: manager`` set, so the static
validator (running before ansible) finds every group the swarm deploy
will use.

Inputs (env): ``APP_ID``, ``INV_PATH`` (default ``/tmp/inv/devices.yml``).
"""

from __future__ import annotations

import os
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.env.parser import parse_static_env
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps
from utils.roles.meta_lookup import get_role_default_placement

_ROLES_DIR = PROJECT_ROOT / "roles"

_DOCKER_VARS: dict[str, str] = {
    "ansible_connection": "docker",
    "ansible_python_interpreter": "/usr/bin/python3",
    "ansible_user": "root",
}

# Node base names are the SPOT in default.env (shared with 00_topology.sh); only the
# SWARM_NAME prefix is applied here so host names match the containers. The get()
# keeps SWARM_NAME import-safe; main() enforces it at run time.
_NAMES = parse_static_env(PROJECT_ROOT / "default.env")
_PREFIX = f"{os.environ['SWARM_NAME']}-" if os.environ.get("SWARM_NAME") else ""
_MANAGER = f"{_PREFIX}{_NAMES['INFINITO_SWARM_MGR_NAME']}"
_WORKERS = (
    f"{_PREFIX}{_NAMES['INFINITO_SWARM_WRK1_NAME']}",
    f"{_PREFIX}{_NAMES['INFINITO_SWARM_WRK2_NAME']}",
)
_NFS_SERVER = f"{_PREFIX}{_NAMES['INFINITO_SWARM_NFS_NAME']}"


def _host_topology(app_id: str) -> list[tuple[str, str]]:
    app_hosts: list[tuple[str, str]] = [(app_id, _MANAGER)]
    # svc-swarm-manager is the IS_STACK_HOST marker group; leaking workers into it
    # flips IS_STACK_HOST true on workers and skips the CA fetch. Keep it manager-only.
    if (
        app_id != "svc-swarm-manager"
        and get_role_default_placement(app_id) != "manager"
    ):
        app_hosts.extend((app_id, w) for w in _WORKERS)
    return [
        ("svc-swarm-node", _MANAGER),
        *[("svc-swarm-node", w) for w in _WORKERS],
        ("svc-swarm-manager", _MANAGER),
        ("svc-storage-nfs-client", _MANAGER),
        *[("svc-storage-nfs-client", w) for w in _WORKERS],
        ("svc-storage-nfs-server", _NFS_SERVER),
        *app_hosts,
    ]


def _default_placement_dep_groups(app_id: str) -> list[tuple[str, str]]:
    applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    needed = applications_if_group_and_all_deps(
        applications,
        [app_id],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
    )
    return [
        (role_name, _MANAGER)
        for role_name in sorted(needed)
        if get_role_default_placement(role_name) == "manager"
    ]


def main() -> int:
    if not os.environ.get("SWARM_NAME"):
        raise SystemExit("extend_inventory: SWARM_NAME is required (cluster id)")
    app_id = os.environ["APP_ID"]
    inv_path = Path(os.environ.get("INV_PATH", "/tmp/inv/devices.yml"))  # noqa: S108

    group_hosts = _host_topology(app_id) + _default_placement_dep_groups(app_id)

    inv = load_yaml_any(str(inv_path), default_if_missing={})
    inv.setdefault("all", {}).setdefault("children", {})
    children = inv["all"]["children"]

    for group, host in group_hosts:
        children.setdefault(group, {}).setdefault("hosts", {})
        children[group]["hosts"][host] = dict(_DOCKER_VARS)

    dump_yaml(str(inv_path), inv)
    print(inv_path.read_text())  # nocheck: cache-read — re-reads the file just written
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
