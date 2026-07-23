import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.filter.get.all.invokable_apps import get_all_invokable_apps
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class TestGetAllInvokableApps(unittest.TestCase):
    def setUp(self):
        """Create a temporary roles/ directory with categories.yml and some example roles."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="invokable_apps_test_"))
        self.roles_dir = self.test_dir / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        self.categories_file = self.roles_dir / "categories.yml"

        categories = {
            "roles": {
                "web": {
                    "title": "Web",
                    "invokable": False,
                    "app": {"title": "Applications", "invokable": True},
                    "svc": {"title": "Services", "invokable": False},
                },
                "update": {"title": "Update", "invokable": True},
                "util": {
                    "title": "utils",
                    "invokable": False,
                    "desk": {"title": "Desktop utils", "invokable": True},
                },
            }
        }
        dump_yaml(self.categories_file, categories)

        roles = [
            ("web-app-nextcloud", "web-app-nextcloud"),
            ("web-app-matomo", "matomo-app"),
            ("web-svc-nginx", None),
            ("update", None),
        ]
        for rolename, appid in roles:
            role_dir = self.roles_dir / rolename
            (role_dir / "vars").mkdir(parents=True, exist_ok=True)
            vars_path = role_dir / ROLE_FILE_VARS_MAIN
            data = {}
            if appid:
                data["application_id"] = appid
            dump_yaml(vars_path, data)

    def tearDown(self):
        """Clean up the temporary test directory after each test."""
        shutil.rmtree(self.test_dir)

    def test_get_all_invokable_apps(self):
        """Should return only applications whose role paths match invokable paths."""
        with patch("utils.roles.validation.invokable.PROJECT_ROOT", self.test_dir):
            result = get_all_invokable_apps()

        expected = sorted(
            [
                "web-app-nextcloud",
                "matomo-app",
                "update",
            ]
        )
        self.assertEqual(sorted(result), expected)

    def test_empty_when_no_invokable(self):
        """Should raise RuntimeError if there are no invokable paths in categories.yml."""
        dump_yaml(self.categories_file, {"roles": {"foo": {"invokable": False}}})

        with (
            patch("utils.roles.validation.invokable.PROJECT_ROOT", self.test_dir),
            self.assertRaises(RuntimeError),
        ):
            get_all_invokable_apps()

    def test_empty_when_no_roles(self):
        """Should return an empty list if there are no roles, but categories.yml exists."""
        shutil.rmtree(self.roles_dir)
        self.roles_dir.mkdir(parents=True, exist_ok=True)

        dump_yaml(
            self.categories_file, {"roles": {"web": {"app": {"invokable": True}}}}
        )

        with patch("utils.roles.validation.invokable.PROJECT_ROOT", self.test_dir):
            result = get_all_invokable_apps()

        self.assertEqual(result, [])

    def test_error_when_no_categories_file(self):
        """
        Should raise FileNotFoundError if categories.yml is missing.

        Note: the implementation resolves invokable paths via
        utils.roles.validation.invokable._get_invokable_paths().
        To make the test deterministic, patch this function directly.
        """
        self.categories_file.unlink()

        with (
            patch("utils.roles.validation.invokable.PROJECT_ROOT", self.test_dir),
            patch(
                "utils.roles.validation.invokable._get_invokable_paths",
                side_effect=FileNotFoundError,
            ),
            self.assertRaises(FileNotFoundError),
        ):
            get_all_invokable_apps()


if __name__ == "__main__":
    unittest.main()
