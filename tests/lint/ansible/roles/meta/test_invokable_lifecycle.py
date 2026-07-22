"""Lint guards for ``meta/services.yml.<primary_entity>.lifecycle`` on
invokable roles.

* **Error**: an invokable role MUST declare a ``lifecycle`` on its primary
  entity. Without it, deployment tooling that filters by lifecycle (e.g.
  ``cli meta roles applications type --lifecycles ...``) silently drops
  the role from any selection.
* **Warning** (GitHub Actions annotation via ``utils.annotations.message``):
  an invokable role with a lifecycle outside the CI-tested set is flagged
  so reviewers can see at a glance which apps ship without deploy-test
  coverage. The CI-tested set is the ``INFINITO_LIFECYCLES`` envelope in
  ``default.env`` (single source of truth).

This test does NOT enforce the allowed-value whitelist; that contract is
already covered by ``TestLifecycleAllowedValues`` in
``tests/lint/ansible/roles/meta/test_layout.py``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.roles.lifecycle import tested_lifecycles
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_lifecycle
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

CI_TESTED_LIFECYCLES: frozenset[str] = tested_lifecycles()


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


class TestInvokableRolesUseCITestedLifecycle(unittest.TestCase):
    def test_invokable_roles_use_ci_tested_lifecycle(self) -> None:
        """Emit a warning for each invokable role whose lifecycle is not in
        the CI-tested set. This is informational only -- it never fails the
        test -- so the project can ship pre-alpha or maintenance apps
        without forcing them through deploy CI."""
        offenders: list[tuple[str, str]] = []
        for role_dir in _invokable_role_dirs(PROJECT_ROOT):
            lifecycle = get_role_lifecycle(role_dir, role_name=role_dir.name)
            if lifecycle is None:
                continue
            if lifecycle in CI_TESTED_LIFECYCLES:
                continue
            offenders.append((role_dir.name, lifecycle))

        ci_set = ", ".join(sorted(CI_TESTED_LIFECYCLES))
        for role_name, lifecycle in offenders:
            warning(
                f"{role_name}: lifecycle={lifecycle!r} is outside the "
                f"CI-tested set ({{{ci_set}}}); this app ships without "
                f"deploy-test coverage.",
                title="Invokable role without CI deploy coverage",
                file=f"roles/{role_name}/{ROLE_FILE_META_SERVICES}",
            )

        if offenders and not in_github_actions():
            print()
            print(
                f"[WARNING] Invokable roles with non-CI-tested lifecycle "
                f"({len(offenders)}):"
            )
            for role_name, lifecycle in offenders:
                print(f"- {role_name}: lifecycle={lifecycle}")


if __name__ == "__main__":
    unittest.main()
