from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from cli.administration.roles.marker import MARKER_FILE, marker_text
from plugins.lookup.role_version import LookupModule

ROLE = "web-app-cst-demo"
ORIGIN = "https://example.invalid/demo.git ansible/roles/web-app-cst-demo @ v0.4.3 (commit abc)"


class TestRoleVersion(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.variables = {"playbook_dir": str(self.root)}

    def _place(self, directory: str, version: str) -> None:
        role = self.root / "roles" / directory
        role.mkdir(parents=True)
        (role / MARKER_FILE).write_text(
            marker_text(directory, directory, ORIGIN, version), encoding="utf-8"
        )

    def _lookup(self, application_id: str) -> list[str]:
        return LookupModule().run([application_id], variables=self.variables)

    def test_returns_the_version_the_pull_recorded(self):
        self._place(ROLE, "0.4.3")
        self.assertEqual(["0.4.3"], self._lookup(ROLE))

    def test_a_pull_without_a_version_fails_naming_the_manifests(self):
        self._place(ROLE, "")
        with self.assertRaisesRegex(AnsibleError, "Cargo.toml, pyproject.toml"):
            self._lookup(ROLE)

    def test_a_role_the_pull_did_not_place_fails(self):
        (self.root / "roles" / ROLE).mkdir(parents=True)
        with self.assertRaisesRegex(AnsibleError, "was not placed by a pull"):
            self._lookup(ROLE)

    def test_a_marker_naming_another_directory_fails(self):
        self._place("web-app-cst-other", "0.4.3")
        (self.root / "roles" / "web-app-cst-other").rename(self.root / "roles" / ROLE)
        with self.assertRaisesRegex(AnsibleError, "was not placed by a pull"):
            self._lookup(ROLE)

    def test_an_in_tree_role_is_refused(self):
        with self.assertRaisesRegex(AnsibleError, "is no custom role"):
            self._lookup("web-app-nextcloud")

    def test_exactly_one_term_is_required(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables=self.variables)

    def test_playbook_dir_is_required(self):
        with self.assertRaisesRegex(AnsibleError, "playbook_dir"):
            LookupModule().run([ROLE], variables={})


if __name__ == "__main__":
    unittest.main()
