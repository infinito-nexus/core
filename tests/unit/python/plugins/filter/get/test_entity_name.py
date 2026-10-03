import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.yaml import dump_yaml
from utils.roles.categories import categories_file
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class TestGetEntityNameFilter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.roles_dir = str(Path(self.temp_dir) / "roles")
        Path(self.roles_dir).mkdir(parents=True)
        self.categories_file = str(categories_file(Path(self.temp_dir)))

        categories = {
            "roles": {
                "web": {
                    "app": {"title": "Applications", "invokable": True},
                    "svc": {"title": "Services", "invokable": True},
                },
                "util": {"dsk": {"dev": {"title": "Dev Utilities", "invokable": True}}},
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

        root = patch("utils.roles.categories.PROJECT_ROOT", Path(self.temp_dir))
        root.start()
        self.addCleanup(root.stop)

        entity_root = patch(
            "utils.roles.entity.name.PROJECT_ROOT", Path(self.temp_dir)
        )
        entity_root.start()
        self.addCleanup(entity_root.stop)

        plugin_path = str(Path.cwd() / "plugins" / "filter")
        if plugin_path not in sys.path and Path(plugin_path).is_dir():
            sys.path.insert(0, plugin_path)
        from plugins.filter.get.entity_name import entity_name

        self.entity_name = entity_name

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_entity_name_web_app(self):
        self.assertEqual(self.entity_name("web-app-snipe-it"), "snipe-it")
        self.assertEqual(self.entity_name("web-app-nextcloud"), "nextcloud")
        self.assertEqual(self.entity_name("web-svc-file"), "file")

    def test_entity_name_sys_bkp(self):
        self.assertEqual(
            self.entity_name("sys-ctl-bkp-directory-validator"),
            "directory-validator",
        )

    def test_entity_name_sys_hlth(self):
        self.assertEqual(self.entity_name("sys-ctl-hlth-btrfs"), "btrfs")

    def test_no_category_match(self):
        self.assertEqual(self.entity_name("foobar-role"), "foobar-role")

    def test_exact_category_match_with_parent_prefix_strips(self):
        self.assertEqual(self.entity_name("web-app"), "app")

    def test_exact_category_match_without_parent_prefix(self):
        self.assertEqual(self.entity_name("web"), "")

    def test_role_equal_to_category_path_strips_parent(self):
        self.assertEqual(self.entity_name("svc-db"), "db")

    def _declare(self, role_name, entity_name):
        dump_yaml(
            str(Path(self.roles_dir) / role_name / ROLE_FILE_VARS_MAIN),
            {"application_id": role_name, "entity_name": entity_name},
        )

    def test_declared_entity_name_overrides_the_derivation(self):
        self._declare("web-app-seaweedfs", "seaweedfs-console")
        self.assertEqual(self.entity_name("web-app-seaweedfs"), "seaweedfs-console")

    def test_declared_jinja_expression_falls_back_to_the_derivation(self):
        self._declare("web-app-nextcloud", "{{ application_id | entity_name }}")
        self.assertEqual(self.entity_name("web-app-nextcloud"), "nextcloud")

    def test_role_without_vars_file_falls_back_to_the_derivation(self):
        self.assertEqual(self.entity_name("web-app-mastodon"), "mastodon")


if __name__ == "__main__":
    unittest.main()
