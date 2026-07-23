import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml


class TestGetEntityNameFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.roles_dir = str(Path(self.temp_dir) / "roles")
        Path(self.roles_dir).mkdir(parents=True)
        self.categories_file = str(Path(self.roles_dir) / "categories.yml")

        categories = {
            "roles": {
                "web": {
                    "app": {"title": "Applications", "invokable": True},
                    "svc": {"title": "Services", "invokable": True},
                },
                "util": {
                    "desk": {"dev": {"title": "Dev Utilities", "invokable": True}}
                },
                "sys": {
                    "ctl": {
                        "bkp": {"title": "Backup", "invokable": True},
                        "hlth": {"title": "Health", "invokable": True},
                    },
                },
                "svc": {"db": {"title": "Databases", "invokable": True}},
            }
        }
        dump_yaml(self.categories_file, categories)

        self._cwd = str(Path.cwd())
        os.chdir(self.temp_dir)

        plugin_path = str(Path(self._cwd) / "plugins" / "filter")
        if plugin_path not in sys.path and Path(plugin_path).is_dir():
            sys.path.insert(0, plugin_path)
        from plugins.filter.get.entity_name import get_entity_name

        self.get_entity_name = get_entity_name

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.temp_dir)

    def test_entity_name_web_app(self):
        self.assertEqual(self.get_entity_name("web-app-snipe-it"), "snipe-it")
        self.assertEqual(self.get_entity_name("web-app-nextcloud"), "nextcloud")
        self.assertEqual(self.get_entity_name("web-svc-file"), "file")

    def test_entity_name_sys_bkp(self):
        self.assertEqual(
            self.get_entity_name("sys-ctl-bkp-directory-validator"),
            "directory-validator",
        )

    def test_entity_name_sys_hlth(self):
        self.assertEqual(self.get_entity_name("sys-ctl-hlth-btrfs"), "btrfs")

    def test_no_category_match(self):
        self.assertEqual(self.get_entity_name("foobar-role"), "foobar-role")

    def test_exact_category_match_with_parent_prefix_strips(self):
        self.assertEqual(self.get_entity_name("web-app"), "app")

    def test_exact_category_match_without_parent_prefix(self):
        self.assertEqual(self.get_entity_name("web"), "")

    def test_role_equal_to_category_path_strips_parent(self):
        self.assertEqual(self.get_entity_name("svc-db"), "db")


if __name__ == "__main__":
    unittest.main()
