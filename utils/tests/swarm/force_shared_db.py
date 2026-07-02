#!/usr/bin/env python3
"""Force ``shared: true`` on every svc-db-* provider service in the swarm-test
inventory host_vars.

Swarm-test only (called by the swarm matrix after provision). In swarm an
embedded per-app database (``shared: false``) resolves to a per-app mariadb
whose volume is NFS-backed with no placement pin — InnoDB on NFS plus a
free-floating task is unsupported (locking, split-brain). Embedded DBs are a
compose-only pattern. Flipping every consumer's DB service to ``shared: true``
routes it to the central svc-db-* provider (as the baseline variant does), so
no per-app DB is scheduled in swarm.

Inputs (env): ``INV_DIR`` — inventory dir holding ``host_vars/*.yml``
(default ``/tmp/inv``).
"""

from __future__ import annotations

import os
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_ROLES_DIR = PROJECT_ROOT / "roles"


def db_provider_service_keys(roles_dir: Path) -> set[str]:
    """Top-level provider service keys declared by every svc-db-* role."""
    keys: set[str] = set()
    for role_dir in sorted(roles_dir.glob("svc-db-*")):
        services_file = role_dir / ROLE_FILE_META_SERVICES
        if not services_file.exists():
            continue
        services = load_yaml_any(services_file)
        if not isinstance(services, dict):
            continue
        for key, entry in services.items():
            if isinstance(entry, dict) and any(
                flag in entry for flag in ("enabled", "shared", "provides")
            ):
                keys.add(str(key))
    return keys


def force_shared_true(host_vars_file: Path, db_keys: set[str]) -> bool:
    """Set ``shared: true`` on any DB-provider service already present under
    ``applications.<app>.services.<key>`` in host_vars_file. Only existing
    entries are touched. Returns True if the file changed."""
    if not host_vars_file.exists():
        return False

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    with host_vars_file.open("r", encoding="utf-8") as f:
        doc = yaml_rt.load(f)

    if not isinstance(doc, CommentedMap):
        return False
    applications = doc.get("applications")
    if not isinstance(applications, CommentedMap):
        return False

    changed = False
    for app_id, app_data in applications.items():
        if not isinstance(app_data, CommentedMap):
            continue
        svc_map = app_data.get("services")
        if not isinstance(svc_map, CommentedMap):
            continue
        for svc_name, svc in svc_map.items():
            if (
                svc_name in db_keys
                and isinstance(svc, CommentedMap)
                and svc.get("shared") is not True
            ):
                svc["shared"] = True
                changed = True
                print(
                    f"[INFO] swarm force-shared: "
                    f"{app_id}.services.{svc_name} → shared=true"
                )

    if changed:
        with host_vars_file.open("w", encoding="utf-8") as f:
            yaml_rt.dump(doc, f)
    return changed


def main() -> int:
    inv_dir = Path(os.environ.get("INV_DIR", "/tmp/inv"))  # noqa: S108 - ephemeral swarm-test inventory path, overridable via INV_DIR
    host_vars_dir = inv_dir / "host_vars"
    if not host_vars_dir.is_dir():
        return 0
    db_keys = db_provider_service_keys(_ROLES_DIR)
    if not db_keys:
        return 0
    for host_vars_file in sorted(host_vars_dir.glob("*.yml")):
        force_shared_true(host_vars_file, db_keys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
