"""Lint guard: every service that mounts a backed-up named volume declares whether a backup must stop it.

``services.<key>.backup.stop_required`` is a literal boolean on every
service a role's ``meta/volumes.yml`` mounts a ``type: volume`` into, so that
baudolo stopping the container or copying it live is a written decision, not
the silent default.

Exempt: services whose ``backup.disabled`` is true (nothing is copied),
services whose every mounted named volume declares ``backup: false`` (baudolo
skips those volumes), and services without their own ``image`` or ``custom``
build, which the ``backup_image`` lookup cannot match and whose owner carries
the marker.
"""

from __future__ import annotations

import unittest
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


def _mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = load_yaml_any(str(path))
    return loaded if isinstance(loaded, dict) else {}


def _backed_up_by_service(volumes: dict[str, Any]) -> dict[str, bool]:
    backed_up: dict[str, bool] = defaultdict(bool)
    for volume in volumes.values():
        if not isinstance(volume, dict) or volume.get("type") != "volume":
            continue
        for mount in volume.get("mounts") or []:
            if isinstance(mount, dict) and mount.get("service"):
                service = str(mount["service"])
                backed_up[service] |= volume.get("backup") is not False
    return dict(backed_up)


def offenders() -> list[str]:
    found: list[str] = []
    for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
        services = _mapping(role_dir / ROLE_FILE_META_SERVICES)
        backed_up = _backed_up_by_service(_mapping(role_dir / ROLE_FILE_META_VOLUMES))
        for key in sorted(key for key, value in backed_up.items() if value):
            service = services.get(key)
            if not isinstance(service, dict):
                continue
            if not (service.get("image") or service.get("custom")):
                continue
            backup = service.get("backup") or {}
            if backup.get("disabled") is True:
                continue
            if not isinstance(backup.get("stop_required"), bool):
                found.append(f"{role_dir.name}: services.{key}")
    return found


class TestBackupStopDecisionDeclared(unittest.TestCase):
    def test_every_volume_service_declares_its_stop_decision(self) -> None:
        found = offenders()
        self.assertEqual(
            [],
            found,
            f"{len(found)} service(s) mount a backed-up named volume without "
            "deciding whether a backup must stop them. Add `backup: "
            "stop_required: true` when the container has to be stopped "
            "before its volumes are copied, `false` when a live copy of every "
            "mounted volume is consistent:\n"
            + "\n".join(f"  - {entry}" for entry in found),
        )


if __name__ == "__main__":
    unittest.main()
