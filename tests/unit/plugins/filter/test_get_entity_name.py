import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml


class TestGetEntityNameFilter(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for roles and categories.yml
        self.temp_dir = tempfile.mkdtemp()
        self.roles_dir = str(Path(self.temp_dir) / "roles")
        Path(self.roles_dir).mkdir(parents=True)
        self.categories_file = str(Path(self.roles_dir) / "categories.yml")

        # Minimal categories.yml for tests
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
                    # falls du 'core' o. ä. brauchst, hier ergänzen
                },
                # 'svc' ist in deinem echten Baum top-level, nicht unter 'sys'
                "svc": {"db": {"title": "Databases", "invokable": True}},
            }
        }
        dump_yaml(self.categories_file, categories)

        # Patch working directory so plugin finds the test categories.yml
        self._cwd = str(Path.cwd())
        os.chdir(self.temp_dir)

        # Make sure plugins/filter directory is on sys.path
        plugin_path = str(Path(self._cwd) / "plugins" / "filter")
        if plugin_path not in sys.path and Path(plugin_path).is_dir():
            sys.path.insert(0, plugin_path)
        # Import plugin fresh each time
        from plugins.filter.get_entity_name import get_entity_name

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
        # Unknown category, should return input
        self.assertEqual(self.get_entity_name("foobar-role"), "foobar-role")

    def test_exact_category_match(self):
        self.assertEqual(self.get_entity_name("web-app"), "")


if __name__ == "__main__":
    unittest.main()
