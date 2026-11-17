from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.custom import (
    MARKER_FILE,
    MARKER_HEADER,
    is_custom,
    is_custom_path,
    manifest_version,
    resolve_role_version,
)
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

CARGO = '[package]\nname = "x"\nversion = "0.4.3"\n'
PYPROJECT = '[project]\nname = "x"\nversion = "7.2.0"\n'
PACKAGE_JSON = '{"name": "x", "version": "2.3.0"}'


def _repo(**files: str):
    return files.get


class TestManifestVersion(unittest.TestCase):
    def test_cargo_package_version(self):
        self.assertEqual("0.4.3", manifest_version(_repo(**{"Cargo.toml": CARGO})))

    def test_cargo_workspace_package_version(self):
        text = '[workspace.package]\nversion = "1.2.3"\n'
        self.assertEqual("1.2.3", manifest_version(_repo(**{"Cargo.toml": text})))

    def test_pyproject_project_version(self):
        self.assertEqual(
            "7.2.0", manifest_version(_repo(**{"pyproject.toml": PYPROJECT}))
        )

    def test_package_json_version(self):
        self.assertEqual(
            "2.3.0", manifest_version(_repo(**{"package.json": PACKAGE_JSON}))
        )

    def test_cargo_wins_over_pyproject_and_package_json(self):
        files = {
            "Cargo.toml": CARGO,
            "pyproject.toml": PYPROJECT,
            "package.json": PACKAGE_JSON,
        }
        self.assertEqual("0.4.3", manifest_version(_repo(**files)))

    def test_a_workspace_inherited_cargo_version_falls_through(self):
        files = {
            "Cargo.toml": "[package]\nversion.workspace = true\n",
            "pyproject.toml": PYPROJECT,
        }
        self.assertEqual("7.2.0", manifest_version(_repo(**files)))

    def test_a_dynamic_pyproject_version_declares_none(self):
        text = '[project]\nname = "x"\ndynamic = ["version"]\n'
        self.assertEqual("", manifest_version(_repo(**{"pyproject.toml": text})))

    def test_a_value_that_is_no_semver_is_passed_over(self):
        files = {
            "Cargo.toml": '[package]\nversion = "latest"\n',
            "package.json": PACKAGE_JSON,
        }
        self.assertEqual("2.3.0", manifest_version(_repo(**files)))

    def test_a_prerelease_semver_counts(self):
        text = '[package]\nversion = "1.0.0-rc.1+build.5"\n'
        self.assertEqual(
            "1.0.0-rc.1+build.5", manifest_version(_repo(**{"Cargo.toml": text}))
        )

    def test_a_version_with_a_trailing_newline_is_passed_over(self):
        files = {
            "Cargo.toml": '[package]\nversion = "1.0.0\\n"\n',
            "package.json": PACKAGE_JSON,
        }
        self.assertEqual("2.3.0", manifest_version(_repo(**files)))

    def test_a_version_of_non_ascii_digits_is_passed_over(self):
        files = {
            "Cargo.toml": '[package]\nversion = "١.٢.٣"\n',
            "package.json": PACKAGE_JSON,
        }
        self.assertEqual("2.3.0", manifest_version(_repo(**files)))

    def test_a_too_deeply_nested_manifest_declares_none(self):
        files = {"package.json": "[" * 100000 + "]" * 100000}
        self.assertEqual("", manifest_version(_repo(**files)))

    def test_unparsable_manifests_declare_none(self):
        files = {"Cargo.toml": "[package\n", "package.json": "{not json"}
        self.assertEqual("", manifest_version(_repo(**files)))

    def test_a_repository_without_manifests_declares_none(self):
        self.assertEqual("", manifest_version(_repo()))


class TestIsCustom(unittest.TestCase):
    def test_reserved_prefix_is_custom(self):
        self.assertTrue(is_custom("web-app-cst-security-check"))

    def test_in_tree_application_is_not_custom(self):
        self.assertFalse(is_custom("web-app-nextcloud"))

    def test_category_name_alone_is_not_custom(self):
        self.assertFalse(is_custom("web-app-cst"))


class TestIsCustomPath(unittest.TestCase):
    def test_file_in_a_placed_custom_role(self):
        self.assertTrue(
            is_custom_path(f"roles/web-app-cst-store/{ROLE_FILE_TASKS_MAIN}")
        )

    def test_file_in_an_in_tree_role(self):
        self.assertFalse(
            is_custom_path(f"roles/web-app-nextcloud/{ROLE_FILE_TASKS_MAIN}")
        )

    def test_custom_prefix_outside_roles(self):
        self.assertFalse(is_custom_path("docs/web-app-cst-store/README.md"))

    def test_roles_directory_itself(self):
        self.assertFalse(is_custom_path("roles"))


class TestResolveRoleVersion(unittest.TestCase):
    PIN = "full-v{{ lookup('role_version', 'web-app-cst-store') }}"

    def _roles(self, marker: str | None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        roles = Path(tmp.name)
        if marker is not None:
            role = roles / "web-app-cst-store"
            role.mkdir()
            (role / MARKER_FILE).write_text(marker, encoding="utf-8")
        return roles

    def test_a_pulled_version_replaces_the_lookup(self):
        roles = self._roles(
            f"{MARKER_HEADER}\ndirectory: web-app-cst-store\nversion: 0.3.4\n"
        )
        self.assertEqual(resolve_role_version(self.PIN, roles), "full-v0.3.4")

    def test_a_marker_without_version_keeps_the_lookup(self):
        roles = self._roles(f"{MARKER_HEADER}\ndirectory: web-app-cst-store\n")
        self.assertEqual(resolve_role_version(self.PIN, roles), self.PIN)

    def test_a_role_without_marker_keeps_the_lookup(self):
        self.assertEqual(resolve_role_version(self.PIN, self._roles(None)), self.PIN)

    def test_a_plain_version_passes_unchanged(self):
        self.assertEqual(resolve_role_version("1.2.3", self._roles(None)), "1.2.3")


if __name__ == "__main__":
    unittest.main()
