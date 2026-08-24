# Unit tests for the get_category_entries Ansible filter plugin (unittest version).

import tempfile
import unittest
from pathlib import Path

from plugins.filter.get.category_entries import get_category_entries


class TestGetCategoryEntries(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_empty_when_roles_dir_missing(self):
        """If the roles directory does not exist, the filter must return an empty list."""
        missing_dir = self.tmp / "no_such_roles_dir"
        self.assertFalse(missing_dir.exists())
        self.assertEqual(
            get_category_entries("docker-", roles_path=str(missing_dir)), []
        )

    def test_matches_prefix_and_sorts(self):
        """
        The filter should return only directory names starting with the prefix,
        and the result must be sorted.
        """
        roles_dir = self.tmp / "roles"
        roles_dir.mkdir()

        (roles_dir / "docker-nginx").mkdir()
        (roles_dir / "docker-postgres").mkdir()
        (roles_dir / "web-app-keycloak").mkdir()
        (roles_dir / "docker-redis").mkdir()

        (roles_dir / "docker-file").write_text("not a directory")

        result = get_category_entries("docker-", roles_path=str(roles_dir))
        self.assertEqual(result, ["docker-nginx", "docker-postgres", "docker-redis"])

    def test_ignores_non_directories(self):
        """Non-directory entries under roles/ must be ignored."""
        roles_dir = self.tmp / "roles"
        roles_dir.mkdir()

        (roles_dir / "docker-engine").mkdir()
        (roles_dir / "docker-engine.txt").write_text("file, should be ignored")

        result = get_category_entries("docker-", roles_path=str(roles_dir))
        self.assertEqual(result, ["docker-engine"])

    def test_respects_custom_roles_path(self):
        """When roles_path is provided, the filter should use it instead of 'roles'."""
        custom_roles = self.tmp / "custom" / "rolesdir"
        custom_roles.mkdir(parents=True)

        (custom_roles / "docker-a").mkdir()
        (custom_roles / "docker-b").mkdir()
        (custom_roles / "other-c").mkdir()

        result = get_category_entries("docker-", roles_path=str(custom_roles))
        self.assertEqual(result, ["docker-a", "docker-b"])

    def test_empty_prefix_returns_all_roles_sorted(self):
        """If an empty prefix is passed, the filter should return all role directories (sorted)."""
        roles_dir = self.tmp / "roles"
        roles_dir.mkdir()

        (roles_dir / "a-role").mkdir()
        (roles_dir / "c-role").mkdir()
        (roles_dir / "b-role").mkdir()

        result = get_category_entries("", roles_path=str(roles_dir))
        self.assertEqual(result, ["a-role", "b-role", "c-role"])


if __name__ == "__main__":
    unittest.main()
