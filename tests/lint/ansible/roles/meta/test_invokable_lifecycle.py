"""Lint guard for ``meta/services.yml.<primary_entity>.lifecycle`` on
invokable roles.

An invokable role MUST declare a ``lifecycle`` on its primary entity. Without
it, deployment tooling that filters by lifecycle (e.g.
``cli meta roles applications type --lifecycles ...``) silently drops the role
from any selection.

This test does NOT enforce the allowed-value whitelist; that contract is
already covered by ``TestLifecycleAllowedValues`` in
``tests/lint/ansible/roles/meta/test_layout.py``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.roles.meta_lookup import get_role_lifecycle
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _invokable_role_dirs(root: Path) -> list[Path]:
    roles_dir = root / "roles"
    if not roles_dir.is_dir():
        return []
    invokable_paths = _get_invokable_paths()
    return sorted(
        (
            p
            for p in roles_dir.iterdir()
            if p.is_dir() and _is_role_invokable(p.name, invokable_paths)
        ),
        key=lambda p: p.name,
    )


class TestInvokableRolesHaveLifecycle(unittest.TestCase):
    def test_invokable_roles_declare_lifecycle(self) -> None:
        missing: list[str] = []
        for role_dir in _invokable_role_dirs(PROJECT_ROOT):
            if get_role_lifecycle(role_dir, role_name=role_dir.name):
                continue
            missing.append(role_dir.name)

        if missing:
            details = "\n".join(f"  - {name}" for name in missing)
            self.fail(
                "Invokable roles missing `lifecycle` on their primary entity "
                "in meta/services.yml (lifecycle-filtered deploy tooling "
                "will silently drop them):\n" + details
            )


if __name__ == "__main__":
    unittest.main()
