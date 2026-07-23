"""Validate every ``roles/<role>/meta/volumes.yml`` against the
canonical mount schema enforced by ``utils.roles.applications.mounts``.

Canonical shape is the dict-of-dicts form: the YAML key is the semantic
short name, and the entry body carries explicit ``type:`` plus
optional ``name:`` (container volume name, defaults to the key for
``type: volume``), ``source:``, ``mounts:``, ``nfs:`` etc. See
``utils/roles/applications/mounts.py`` for the per-entry schema contract.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mounts import validate_volumes_meta
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

if TYPE_CHECKING:
    from pathlib import Path

from . import PROJECT_ROOT


def _roles_root() -> Path:
    return PROJECT_ROOT / "roles"


class TestVolumesYamlSchema(unittest.TestCase):
    def test_all_roles_volumes_yml_match_schema(self) -> None:
        roles_root = _roles_root()
        if not roles_root.is_dir():
            self.skipTest(f"roles/ not present at {roles_root}")

        violations: list[str] = []
        for volumes_yml in sorted(roles_root.glob(f"*/{ROLE_FILE_META_VOLUMES}")):
            role_id = volumes_yml.parent.parent.name
            try:
                content = load_yaml_any(str(volumes_yml), default_if_missing={})
            except Exception as exc:
                violations.append(f"{role_id}: YAML parse error: {exc}")
                continue
            if content is None or content == {}:
                continue
            if not isinstance(content, dict):
                violations.append(
                    f"{role_id}: meta/volumes.yml top-level must be a "
                    f"mapping (dict-of-dicts canonical shape), got "
                    f"{type(content).__name__}"
                )
                continue
            violations.extend(validate_volumes_meta(content, role_id))

        if violations:
            self.fail(
                "meta/volumes.yml schema violations:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
