from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.meta.roles.applications.new_in_branch import (
    new_application_roles,
    roles_on_branch,
    roles_present_in_ref,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


def _mk_role(roles_dir: Path, name: str, *, application_id: str | None) -> None:
    vars_file = roles_dir / name / ROLE_FILE_VARS_MAIN
    vars_file.parent.mkdir(parents=True, exist_ok=True)
    body = f"application_id: {application_id}\n" if application_id else "other: 1\n"
    vars_file.write_text(body, encoding="utf-8")


def _checkout(case: unittest.TestCase, root: Path) -> Path:
    """
    Args:
        case: test whose environment loses the hook-scoped GIT_* variables
            until its cleanup runs, so git cannot reach an outer repository.
        root: directory initialised as a repository that ignores custom roles.

    Returns:
        the ``roles/`` directory of the new checkout.
    """
    scoped = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    env = {key: value for key, value in os.environ.items() if key not in scoped}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    patcher = mock.patch.dict(os.environ, env, clear=True)
    patcher.start()
    case.addCleanup(patcher.stop)
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / ".gitignore").write_text("roles/web-app-cst-*\n", encoding="utf-8")
    return root / "roles"


class TestNewInBranch(unittest.TestCase):
    def test_returns_empty_when_ref_unresolvable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            _mk_role(roles_dir, "web-app-new", application_id="web-app-new")
            self.assertIsNone(roles_present_in_ref(roles_dir, "origin/main"))
            self.assertEqual(new_application_roles(roles_dir, "origin/main"), [])

    def test_new_app_roles_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = _checkout(self, Path(td))
            _mk_role(roles_dir, "web-app-old", application_id="web-app-old")
            _mk_role(roles_dir, "web-app-new", application_id="web-app-new")
            _mk_role(roles_dir, "helper-new", application_id=None)
            with mock.patch(
                "cli.meta.roles.applications.new_in_branch.roles_present_in_ref",
                return_value={"web-app-old"},
            ):
                result = new_application_roles(roles_dir, "origin/main")
        self.assertEqual(result, ["web-app-new"])

    def test_a_role_placed_under_an_ignored_path_is_not_new(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = _checkout(self, Path(td))
            _mk_role(roles_dir, "web-app-new", application_id="web-app-new")
            _mk_role(
                roles_dir,
                "web-app-cst-skeleton-none",
                application_id="web-app-cst-skeleton-none",
            )
            with mock.patch(
                "cli.meta.roles.applications.new_in_branch.roles_present_in_ref",
                return_value=set(),
            ):
                result = new_application_roles(roles_dir, "origin/main")
        self.assertEqual(result, ["web-app-new"])

    def test_the_branch_lists_tracked_and_untracked_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = _checkout(self, Path(td))
            _mk_role(roles_dir, "web-app-staged", application_id="web-app-staged")
            _mk_role(roles_dir, "web-app-loose", application_id="web-app-loose")
            subprocess.run(
                ["git", "-C", td, "add", f"roles/web-app-staged/{ROLE_FILE_VARS_MAIN}"],
                check=True,
            )
            self.assertEqual(
                roles_on_branch(roles_dir), {"web-app-staged", "web-app-loose"}
            )


if __name__ == "__main__":
    unittest.main()
