import unittest
import importlib.util
import os

TEST_DIR = os.path.dirname(__file__)
PLUGIN_PATH = os.path.abspath(
    os.path.join(
        TEST_DIR,
        "../../../../../roles/sys-ctl-bkp-docker-2-loc/filter_plugins/find_dock_val_by_bkp_entr.py",
    )
)

spec = importlib.util.spec_from_file_location("find_dock_val_by_bkp_entr", PLUGIN_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
find_dock_val_by_bkp_entr = mod.find_dock_val_by_bkp_entr


class TestFindDockValByBkpEntr(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "app1": {
                "services": {
                    "svc1": {
                        "name": "svc1",
                        "image": "nginx:latest",
                        "custom_field": "foo",
                        "backup": {"enabled": True, "mode": "full"},
                    },
                    "svc2": {
                        "name": "svc2",
                        "image": "redis:alpine",
                        "custom_field": "bar",
                        "backup": {
                            "enabled": False,
                        },
                    },
                    "svc3": {"name": "svc3", "image": "postgres:alpine"},
                }
            },
            "app2": {
                "services": {
                    "svcA": {
                        "name": "svcA",
                        "image": "alpine:latest",
                        "backup": {"enabled": 1, "mode": "diff"},
                    },
                    "svcB": {
                        "name": "svcB",
                        "image": "ubuntu:latest",
                        "backup": {
                            "something_else": True,
                        },
                    },
                }
            },
            "app_no_docker": {"meta": "should be skipped"},
        }

    def test_finds_services_with_enabled_backup_name(self):
        # All service names where backup.enabled is truthy (sorted)
        result = find_dock_val_by_bkp_entr(self.applications, "enabled", "name")
        self.assertEqual(result, ["svc1", "svcA"])

    def test_finds_services_with_enabled_backup_image(self):
        # All images where backup.enabled is truthy (sorted)
        result = find_dock_val_by_bkp_entr(self.applications, "enabled", "image")
        self.assertEqual(result, ["alpine:latest", "nginx:latest"])

    def test_finds_services_with_enabled_backup_custom_field(self):
        # All custom_field values where backup.enabled is truthy
        result = find_dock_val_by_bkp_entr(self.applications, "enabled", "custom_field")
        # svcA has no custom_field -> must not appear in the result
        self.assertEqual(result, ["foo"])

    def test_finds_other_backup_keys(self):
        # Services where backup.mode is set (sorted)
        result = find_dock_val_by_bkp_entr(self.applications, "mode", "name")
        self.assertEqual(result, ["svc1", "svcA"])

    def test_returns_empty_list_when_no_match(self):
        # Services where backup.xyz is not set
        result = find_dock_val_by_bkp_entr(self.applications, "doesnotexist", "name")
        self.assertEqual(result, [])

    def test_returns_empty_list_on_empty_input(self):
        result = find_dock_val_by_bkp_entr({}, "enabled", "name")
        self.assertEqual(result, [])

    def test_raises_on_non_dict_input(self):
        with self.assertRaises(Exception):
            find_dock_val_by_bkp_entr(None, "enabled", "name")
        with self.assertRaises(Exception):
            find_dock_val_by_bkp_entr([], "enabled", "name")

    def test_works_with_missing_field(self):
        # mapped_entry missing -> no entry in result
        apps = {"a": {"services": {"x": {"backup": {"enabled": True}}}}}
        result = find_dock_val_by_bkp_entr(apps, "enabled", "foo")
        self.assertEqual(result, [])

    def test_works_with_multiple_matches(self):
        # Two matches, both with enabled, using a custom return field
        apps = {
            "a": {
                "services": {
                    "x": {"backup": {"enabled": True}, "any": "n1"},
                    "y": {"backup": {"enabled": True}, "any": "n2"},
                }
            }
        }
        result = find_dock_val_by_bkp_entr(apps, "enabled", "any")
        self.assertEqual(result, ["n1", "n2"])

    def test_result_is_sorted(self):
        # Results must be sorted lexicographically
        apps = {
            "a": {
                "services": {
                    "x": {"backup": {"enabled": True}, "name": "zeta"},
                    "y": {"backup": {"enabled": True}, "name": "alpha"},
                    "z": {"backup": {"enabled": True}, "name": "mike"},
                }
            }
        }
        result = find_dock_val_by_bkp_entr(apps, "enabled", "name")
        self.assertEqual(result, ["alpha", "mike", "zeta"])


if __name__ == "__main__":
    unittest.main()
