"""Require an explicit ``backup:`` decision on any volume that carries a
nested container data root.

Rationale
=========
A volume mounted at ``/var/lib/docker`` or ``/var/lib/containers`` holds an
inner engine's overlay store. Copying it with rsync is not merely wasteful,
it produces an artifact that cannot be restored: overlay2 encodes a deletion
both as a character device ``0:0`` whiteout and as a ``trusted.overlay.*``
extended attribute, and no rsync in the backup chain carries ``-X``. The
whiteouts also make the copy unwritable onto any overlayfs destination,
which is what turned the ``web-app-matrix`` DR drill red.

Whichever way a role decides, the decision must be written down::

    matrix_mdad_docker:
      type: volume
      name: matrix_mdad_docker
      backup: false

There is no opt-out marker: ``backup: true`` is the way to say "yes, on
purpose".
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_NESTED_DATA_ROOTS = ("/var/lib/docker", "/var/lib/containers")


def _carries_nested_data_root(entry: object) -> bool:
    if not isinstance(entry, dict) or entry.get("type", "volume") != "volume":
        return False
    mounts = entry.get("mounts")
    if not isinstance(mounts, list):
        return False
    return any(
        isinstance(mount, dict) and mount.get("target") in _NESTED_DATA_ROOTS
        for mount in mounts
    )


def _undecided(volumes_path: Path) -> list[str]:
    data = load_yaml_any(volumes_path) or {}
    if not isinstance(data, dict):
        return []
    return [
        name
        for name, entry in data.items()
        if _carries_nested_data_root(entry) and "backup" not in entry
    ]


class TestNestedDataRootBackupDecision(unittest.TestCase):
    def test_nested_data_roots_state_their_backup_intent(self) -> None:
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            volumes_path = role_dir / ROLE_FILE_META_VOLUMES
            if not role_dir.is_dir() or not volumes_path.exists():
                continue
            findings.extend(
                f"{role_dir.name}: {name}" for name in _undecided(volumes_path)
            )

        self.assertFalse(
            findings,
            f"{len(findings)} volume(s) mount a nested container data root "
            f"({', '.join(_NESTED_DATA_ROOTS)}) without an explicit 'backup:' "
            "key in meta/volumes.yml. An overlay store copied by rsync loses "
            "its trusted.overlay.* xattrs and cannot be restored, and its "
            "whiteout character devices cannot be written to an overlayfs "
            "destination. Declare 'backup: false' to exclude it, or "
            "'backup: true' to state the intent:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
