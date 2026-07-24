from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.meta.roles.applications.new_in_branch import (
    new_application_roles,
    roles_present_in_ref,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


def _mk_role(roles_dir: Path, name: str, *, application_id: str | None) -> None:
    vars_file = roles_dir / name / ROLE_FILE_VARS_MAIN
    vars_file.parent.mkdir(parents=True, exist_ok=True)
    body = f"application_id: {application_id}\n" if application_id else "other: 1\n"
    vars_file.write_text(body, encoding="utf-8")


class TestNewInBranch(unittest.TestCase):
    def test_returns_empty_when_ref_unresolvable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            _mk_role(roles_dir, "web-app-new", application_id="web-app-new")
            self.assertIsNone(roles_present_in_ref(roles_dir, "origin/main"))
            self.assertEqual(new_application_roles(roles_dir, "origin/main"), [])

    def test_new_app_roles_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            _mk_role(roles_dir, "web-app-old", application_id="web-app-old")
            _mk_role(roles_dir, "web-app-new", application_id="web-app-new")
            _mk_role(roles_dir, "helper-new", application_id=None)
            with mock.patch(
                "cli.meta.roles.applications.new_in_branch.roles_present_in_ref",
                return_value={"web-app-old"},
            ):
                result = new_application_roles(roles_dir, "origin/main")
        self.assertEqual(result, ["web-app-new"])


if __name__ == "__main__":
    unittest.main()
