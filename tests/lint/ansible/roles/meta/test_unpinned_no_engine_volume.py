"""A role that is NOT placement-pinned must not own a database / queue / index
engine's on-disk data volume.

NFS placement is derived from the role's ``placement`` (see
``plugins/filter/compose_volumes.py``): an unpinned role's volumes are bound to
the shared NFS mount so they survive a node reschedule, while a pinned
(``placement: manager``) role keeps its volumes node-local. A database,
message-queue or search-index engine's on-disk state CANNOT live on NFS (fsync +
locking corruption). Such state must therefore stay node-local -- which means its
role must be pinned (so the service never leaves the node holding the data), or
the engine must be externalised to a central pinned service. This lint catches an
unpinned role that would otherwise have its engine data silently placed on NFS.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN
from utils.roles.meta_lookup import get_role_placement

from . import PROJECT_ROOT


def _forces_compose_mode(role_dir) -> bool:
    """True iff the role statically pins compose_mode_force to 'compose':
    such a role deploys as a node-local compose stack in swarm, so its
    volumes never land on NFS (see plugins/lookup/compose_volumes.py).
    Jinja-valued forces are treated as not forced (conservative)."""
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    if not vars_file.is_file():
        return False
    try:
        role_vars = load_yaml_any(str(vars_file), default_if_missing={})
    except Exception:
        return False
    if not isinstance(role_vars, dict):
        return False
    return str(role_vars.get("compose_mode_force", "")).strip() == "compose"


_ENGINE_TARGET_PREFIXES = (
    "/var/lib/postgresql",
    "/var/lib/mysql",
    "/var/lib/mariadb",
    "/var/lib/ldap",
    "/etc/ldap/slapd.d",
    "/var/lib/redis",
    "/var/lib/rabbitmq",
    "/var/lib/mongodb",
    "/data/db",
    "/qdrant",
    "/prometheus",
)
_ENGINE_TARGET_KEYWORDS = (
    "elasticsearch",
    "opensearch",
    "typesense",
    "clickhouse",
    "/solr",
)


def _is_engine_target(target: str) -> bool:
    t = (target or "").strip().lower()
    if not t:
        return False
    if any(t.startswith(p) for p in _ENGINE_TARGET_PREFIXES):
        return True
    return any(k in t for k in _ENGINE_TARGET_KEYWORDS)


class TestUnpinnedNoEngineVolume(unittest.TestCase):
    def test_unpinned_roles_declare_no_engine_data_volume(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            self.skipTest(f"roles/ not present at {roles_root}")

        violations: list[str] = []
        for volumes_yml in sorted(roles_root.glob(f"*/{ROLE_FILE_META_VOLUMES}")):
            role_id = volumes_yml.parent.parent.name
            if str(get_role_placement(role_id) or "").strip().lower() == "manager":
                continue
            if _forces_compose_mode(volumes_yml.parent.parent):
                continue
            try:
                content = load_yaml_any(str(volumes_yml), default_if_missing={})
            except Exception as exc:
                violations.append(f"{role_id}: YAML parse error: {exc}")
                continue
            if not isinstance(content, dict):
                continue
            for key, entry in content.items():
                if not isinstance(entry, dict) or entry.get("type") != "volume":
                    continue
                if entry.get("nfs") is False:
                    continue
                for mount in entry.get("mounts") or []:
                    if not isinstance(mount, dict):
                        continue
                    if _is_engine_target(mount.get("target", "")):
                        violations.append(
                            f"{role_id}: volume '{key}' mounts engine data at "
                            f"'{mount.get('target')}' but the role is not pinned. "
                            "Engine state cannot live on NFS; pin the role "
                            "(placement: manager) or externalise the engine."
                        )
                        break

        if violations:
            self.fail(
                "unpinned roles with NFS-hostile engine data volumes:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
