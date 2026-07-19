#!/usr/bin/env python3
"""Extend the provisioned test inventory with host-topology placements
plus the dep-walked ``placement: manager`` set, so the static
validator (running before ansible) finds every group the swarm deploy
will use.

The dep walk delegates to ``derive_includes`` so the group set matches
the provisioned include/credential closure.

Node base names are the SPOT in default.env (shared with scripts/tests/deploy/swarm/utils/topology/base.sh);
only the SWARM_NAME prefix is applied here so host names match the
containers. The env get() keeps SWARM_NAME import-safe; main() enforces it
at run time.

The backup host is NOT appended to the cluster inventory: it lives in a
sibling ``backup.yml`` next to ``INV_PATH`` (same host_vars dir), deployed
as a second play after the cluster one. Without a svc-swarm-node group that
play resolves DEPLOYMENT_MODE=compose and IS_STACK_HOST=true on the backup
host, so the backup roles run without cluster-membership special cases.

Inputs (env): ``APP_ID``, ``INV_PATH`` (default ``/tmp/inv/devices.yml``).
Optional ``INFINITO_APP_VARIANTS`` (consumed by ``derive_includes``).
"""

from __future__ import annotations

import os
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.env.parser import parse_static_env
from utils.roles.meta_lookup import get_role_placement
from utils.tests.swarm.derive_includes import derive_includes

_DOCKER_VARS: dict[str, str] = {
    "ansible_connection": "docker",
    "ansible_python_interpreter": "/usr/bin/python3",
    "ansible_user": "root",
}

_NAMES = parse_static_env(PROJECT_ROOT / "default.env")
_PREFIX = f"{os.environ['SWARM_NAME']}-" if os.environ.get("SWARM_NAME") else ""
_MANAGER = f"{_PREFIX}{_NAMES['INFINITO_SWARM_MGR_NAME']}"
_WORKERS = (
    f"{_PREFIX}{_NAMES['INFINITO_SWARM_WRK1_NAME']}",
    f"{_PREFIX}{_NAMES['INFINITO_SWARM_WRK2_NAME']}",
)
_NFS_SERVER = f"{_PREFIX}{_NAMES['INFINITO_SWARM_NFS_NAME']}"
_BACKUP = f"{_PREFIX}{_NAMES['INFINITO_SWARM_BACKUP_NAME']}"


def _host_topology(app_id: str) -> list[tuple[str, str]]:
    app_hosts: list[tuple[str, str]] = [(app_id, _MANAGER)]
    # Exception: svc-swarm-manager is the IS_STACK_HOST marker group; leaking
    # workers into it flips IS_STACK_HOST true on workers and skips the CA
    # fetch. Keep it manager-only.
    if app_id != "svc-swarm-manager" and get_role_placement(app_id) != "manager":
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


def _placement_dep_groups(app_id: str) -> list[tuple[str, str]]:
    return [
        (role_name, _MANAGER)
        for role_name in derive_includes(app_id)
        if get_role_placement(role_name) == "manager"
    ]


def main() -> int:
    if not os.environ.get("SWARM_NAME"):
        raise SystemExit("extend_inventory: SWARM_NAME is required (cluster id)")
    app_id = os.environ["APP_ID"]
    inv_path = Path(os.environ.get("INV_PATH", "/tmp/inv/devices.yml"))  # noqa: S108 - ephemeral swarm-test inventory path, overridable via INV_PATH

    closure = derive_includes(app_id)
    group_hosts = _host_topology(app_id) + _placement_dep_groups(app_id)
    if "svc-bkp-volume-2-local" in closure:
        group_hosts.append(("svc-bkp-volume-2-local", _MANAGER))
    if "svc-bkp-secrets-2-local" in closure:
        group_hosts.append(("svc-bkp-secrets-2-local", _MANAGER))
    if "svc-bkp-nfs-2-local" in derive_includes("svc-storage-nfs-server"):
        group_hosts.append(("svc-bkp-nfs-2-local", _NFS_SERVER))

    inv = load_yaml_any(str(inv_path), default_if_missing={})
    inv.setdefault("all", {}).setdefault("children", {})
    children = inv["all"]["children"]

    for group, host in group_hosts:
        children.setdefault(group, {}).setdefault("hosts", {})
        children[group]["hosts"][host] = dict(_DOCKER_VARS)

    dump_yaml(str(inv_path), inv)
    print(inv_path.read_text())  # nocheck: cache-read — re-reads the file just written

    backup_inv = {
        "all": {
            "children": {
                group: {"hosts": {_BACKUP: dict(_DOCKER_VARS)}}
                for group in ("svc-bkp-remote-2-local", "svc-bkp-local-2-device")
            }
        }
    }
    backup_path = inv_path.parent / "backup.yml"
    dump_yaml(str(backup_path), backup_inv)
    print(backup_path.read_text())  # nocheck: cache-read
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
