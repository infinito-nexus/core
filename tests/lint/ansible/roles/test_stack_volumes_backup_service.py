"""Require the volume-2-local backup service flag on stack roles with
named volumes.

Rationale
=========
``svc-bkp-volume-2-local`` backs up named docker volumes, but only
for hosts that carry the role in their inventory group. A stack role
that declares named volumes in ``meta/volumes.yml`` without the
``volume-2-local`` service flag never advertises the backup
dependency, so its data silently stays out of every backup plan. Every
invokable stack role (``templates/compose.yml.j2`` or a
``templates/*.compose.yml.j2`` sibling, see
:func:`utils.roles.mapping.role_is_stack`) that declares at least one
``type: volume`` entry MUST carry the standard consumer flag in
``meta/services.yml``::

    container_backup:
      bond: 1
      enabled: "{{ 'svc-bkp-volume-2-local' in group_names }}"
      shared: true

``enabled`` MUST reference the provider role through the
``in group_names`` idiom; ``shared`` MUST be the literal ``true``
(there is no per-consumer backup instance).

Per-role opt-out
================
Add ``# nocheck: backup-service-flag <reason>`` on the first line of the
role's ``meta/volumes.yml``. Reserved for roles whose volumes provably
hold only reproducible caches or ephemera.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    role_is_stack,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "backup-service-flag"
_SERVICE_KEY = "container_backup"
_PROVIDER_ROLE = "svc-bkp-volume-2-local"
_GROUP_NAMES_RE = re.compile(
    r"\{\{\s*'" + re.escape(_PROVIDER_ROLE) + r"'\s+in\s+group_names\s*\}\}"
)


def _invokable_prefixes() -> tuple[str, ...]:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "filter"))
    from invokable_paths import get_invokable_paths

    return tuple(get_invokable_paths(suffix="-"))


def _declares_named_volume(volumes_path: Path) -> bool:
    data = load_yaml_any(volumes_path) or {}
    if not isinstance(data, dict):
        return False
    return any(
        isinstance(entry, dict) and entry.get("type", "volume") == "volume"
        for entry in data.values()
    )


def _flag_is_valid(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    enabled = entry.get("enabled")
    if not (isinstance(enabled, str) and _GROUP_NAMES_RE.search(enabled)):
        return False
    return entry.get("shared") is True


class TestStackVolumesBackupService(unittest.TestCase):
    def test_stack_roles_with_volumes_carry_backup_flag(self) -> None:
        prefixes = _invokable_prefixes()
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if not role_dir.is_dir() or not role_dir.name.startswith(prefixes):
                continue
            if role_dir.name == _PROVIDER_ROLE:
                continue
            if not role_is_stack(role_dir):
                continue
            volumes_path = role_dir / ROLE_FILE_META_VOLUMES
            if not volumes_path.exists():
                continue
            first_line = read_text(str(volumes_path)).split("\n", 1)[0]
            if f"nocheck: {_RULE}" in first_line:
                continue
            if not _declares_named_volume(volumes_path):
                continue
            services_path = role_dir / ROLE_FILE_META_SERVICES
            services = (
                load_yaml_any(services_path) or {} if services_path.exists() else {}
            )
            if not _flag_is_valid(services.get(_SERVICE_KEY)):
                findings.append(role_dir.name)

        self.assertFalse(
            findings,
            f"{len(findings)} stack role(s) declare named volumes in "
            f"meta/volumes.yml but miss the '{_SERVICE_KEY}' backup service "
            "flag in meta/services.yml. Add the standard consumer entry "
            "(enabled/shared gated on "
            f"\"'{_PROVIDER_ROLE}' in group_names\") or opt out with "
            f"'# nocheck: {_RULE} <reason>' on the first line of "
            "meta/volumes.yml:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
