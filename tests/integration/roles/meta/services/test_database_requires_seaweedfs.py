"""Integration guard: every ``roles/web-app-*`` role whose ``meta/services.yml``
declares a ``postgres`` or ``mariadb`` service MUST also declare a ``seaweedfs``
object-store service.

Rationale
---------

Hypothesis: a database-backed application almost always also needs object
storage (uploads, media, attachments, exports). Enforcing the co-declaration
keeps object storage from being silently forgotten when a new database-backed
role is added.

Exemption
---------

A role that genuinely does not need object storage carries a file-level
marker within the first lines of its ``meta/services.yml``::

    ---
    # nocheck: seaweedfs-required — <reason>
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.database import RDBMS_SERVICE_KEYS
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "seaweedfs-required"


def _is_truthy_flag(value: object) -> bool:
    """A services flag counts as "on" if it is literal ``True`` or the dynamic
    ``"{{ '<role>' in group_names }}"`` form enforced for service flags."""
    return value is True or (isinstance(value, str) and "in group_names" in value)


class TestDatabaseRequiresSeaweedfs(unittest.TestCase):
    def test_web_app_with_database_declares_seaweedfs_or_is_exempted(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            if not role_name.startswith("web-app-"):
                continue

            services_file: Path = role_dir / ROLE_FILE_META_SERVICES
            if not services_file.is_file():
                continue

            try:
                lines = read_text(str(services_file)).splitlines()
            except (UnicodeDecodeError, PermissionError):
                continue

            if is_suppressed_in_head(lines, _RULE, scan_lines=30):
                continue

            try:
                data = load_yaml_any(str(services_file), default_if_missing={}) or {}
            except Exception as exc:
                offenders.append(f"{role_name}: YAML parse error: {exc}")
                continue
            if not isinstance(data, dict):
                continue

            has_database = any(
                isinstance(data.get(key), dict)
                and _is_truthy_flag(data[key].get("enabled"))
                for key in RDBMS_SERVICE_KEYS
            )
            if not has_database:
                continue

            seaweedfs = data.get("seaweedfs")
            if not (
                isinstance(seaweedfs, dict)
                and _is_truthy_flag(seaweedfs.get("enabled"))
            ):
                offenders.append(
                    f"{role_name}: declares a database (postgres/mariadb) but does "
                    f"not enable a seaweedfs object-store service. Add a seaweedfs "
                    f"service, or a `# nocheck: {_RULE}` marker in the services.yml head."
                )

        if offenders:
            self.fail(
                f"web-app roles with a database MUST declare seaweedfs ({_RULE}):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
