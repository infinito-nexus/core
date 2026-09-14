"""Lint: a role without an external database MUST NOT keep read-write state on
a shared NFS volume.

Under swarm an unpinned role's volumes are rewritten onto the shared NFS export
(``utils/storage/nfs.py``) while its services run one task per node. A role that
declares no RDBMS service keeps its state in-process instead: an embedded SQLite
file, a Mnesia store, a Lucene index. Those writers assume POSIX locking that
NFS does not deliver, so the replicas write the same files over NFS and corrupt
them.

Resolve it by externalising the state into a database service, by taking the
volume off NFS (``nfs: false``) together with a single replica or a manager pin,
or -- when the payload is genuinely share-safe, such as write-once model blobs
or a regenerable asset cache -- with a
``# nocheck: embedded-state-on-nfs <reason>`` marker on the volume entry.

Roles that do declare a database service are out of scope: their shared volumes
carry uploads and media, which several replicas may safely write side by side.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.database import RDBMS_SERVICE_KEYS
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES
from utils.roles.meta_lookup import get_role_mode_enabled
from utils.storage.nfs import swarm_nfs_backed

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "embedded-state-on-nfs"


def _load_services(role_dir: Path) -> dict:
    content = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    return content if isinstance(content, dict) else {}


def _has_rdbms_service(services: dict) -> bool:
    """True when the role runs its own RDBMS, so its state is not in-process.

    A Jinja-valued ``enabled`` counts as enabled: it resolves per inventory, and
    treating it as absent would flag every optionally-attached database.
    """
    for key in RDBMS_SERVICE_KEYS:
        spec = services.get(key)
        if not isinstance(spec, dict):
            continue
        if str(spec.get("enabled", "")).strip().lower() != "false":
            return True
    return False


def _declares_one_replica(spec: object) -> bool:
    return isinstance(spec, dict) and str(spec.get("replicas", "")).strip() == "1"


def _single_replica_service_names(role_id: str, services: dict) -> set[str] | None:
    """Service names that run exactly one task, or ``None`` when the whole role
    does.

    A mount names the service by its rendered ``name``, which defaults to the
    entity key. Replicas resolve service-first and fall back to the primary
    entity, so a pin there covers every service in the role.
    """
    primary = get_entity_name(role_id) or role_id
    if _declares_one_replica(services.get(primary)):
        return None
    return {
        str(spec.get("name", key))
        for key, spec in services.items()
        if _declares_one_replica(spec)
    }


def _key_lines(lines: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for idx, line in enumerate(lines, 1):
        match = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if match and match.group(1) not in found:
            found[match.group(1)] = idx
    return found


def _collect_findings(root: Path) -> list[str]:
    findings: list[str] = []
    for volumes_yml in sorted((root / "roles").glob(f"*/{ROLE_FILE_META_VOLUMES}")):
        role_dir = volumes_yml.parent.parent
        role_id = role_dir.name
        if not get_role_mode_enabled(role_dir, mode="swarm", role_name=role_id):
            continue
        services = _load_services(role_dir)
        if _has_rdbms_service(services):
            continue
        pinned = _single_replica_service_names(role_id, services)
        if pinned is None:
            continue

        content = load_yaml_any(str(volumes_yml), default_if_missing={})
        if not isinstance(content, dict):
            continue
        try:
            lines = read_text(str(volumes_yml)).splitlines()
        except OSError:
            continue
        key_lines = _key_lines(lines)

        for key, entry in content.items():
            if not isinstance(entry, dict) or entry.get("type") != "volume":
                continue
            if not swarm_nfs_backed(
                entry,
                application_id=role_id,
                deployment_mode="swarm",
                storage_backend="nfs",
            ):
                continue
            line = key_lines.get(key)
            if line and is_suppressed_at(lines, line, _RULE, mode="same-or-above"):
                continue
            for mount in entry.get("mounts") or []:
                if not isinstance(mount, dict) or mount.get("read_only") is True:
                    continue
                service = str(mount.get("service", ""))
                if service in pinned:
                    continue
                findings.append(
                    f"{role_id}: volume '{key}' is NFS-backed and mounted "
                    f"read-write by '{service}' at '{mount.get('target')}', "
                    "but the role declares no database service, so this is "
                    "in-process state written by every replica."
                )
                break
    return findings


class TestEmbeddedStateOnNfs(unittest.TestCase):
    def test_databaseless_roles_keep_no_rw_state_on_nfs(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)
        if not findings:
            return
        details = "\n".join(f"  - {f}" for f in findings)
        self.fail(
            f"{len(findings)} NFS-backed volume(s) hold in-process state that "
            "every replica writes. Externalise the state to a database, take "
            "the volume off NFS (`nfs: false`) with a single replica or a "
            "manager pin, or mark a genuinely share-safe payload with "
            "`# nocheck: embedded-state-on-nfs <reason>` on the volume "
            f"entry.\n{details}"
        )


if __name__ == "__main__":
    unittest.main()
