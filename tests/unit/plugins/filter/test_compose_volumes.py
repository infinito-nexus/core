from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict

import yaml
from ansible.errors import AnsibleFilterError


def _ensure_repo_root_on_syspath() -> None:
    this_file = os.path.abspath(__file__)
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(this_file), "..", "..", "..", "..")
    )
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


_ensure_repo_root_on_syspath()

from plugins.filter.compose_volumes import compose_volumes  # noqa: E402


class TestComposeVolumes(unittest.TestCase):
    def _parse_yaml(self, rendered: str) -> Dict[str, Any]:
        self.assertIsInstance(rendered, str)
        data = yaml.safe_load(rendered) if rendered.strip() else {}
        self.assertIsInstance(data, dict)
        self.assertIn("volumes", data)
        self.assertIsInstance(data["volumes"], dict)
        return data

    def _base_apps(self) -> Dict[str, Any]:
        # Per req-008 the materialised payload moved from
        # `applications.<app>.compose.services.<X>` to
        # `applications.<app>.services.<X>`.
        return {
            "app": {
                "services": {
                    "mariadb": {"enabled": False, "shared": False},
                    "redis": {"enabled": False},
                    "oauth2": {"enabled": False},
                }
            }
        }

    # -----------------------------
    # Input validation (strict)
    # -----------------------------
    def test_none_applications_raises(self):
        with self.assertRaises(AnsibleFilterError):
            compose_volumes(None, "app")  # type: ignore[arg-type]

    def test_non_dict_applications_raises(self):
        with self.assertRaises(AnsibleFilterError):
            compose_volumes(["not-a-dict"], "app")  # type: ignore[arg-type]

    def test_empty_application_id_raises(self):
        apps = self._base_apps()
        with self.assertRaises(AnsibleFilterError):
            compose_volumes(apps, "")  # type: ignore[arg-type]

    def test_unknown_application_id_raises(self):
        apps = self._base_apps()
        with self.assertRaises(AnsibleFilterError):
            compose_volumes(apps, "missing-app")

    # -----------------------------
    # Empty but valid
    # -----------------------------
    def test_renders_volumes_key_even_when_empty(self):
        apps = self._base_apps()
        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)
        self.assertEqual(data["volumes"], {})

    # -----------------------------
    # Database volume
    # -----------------------------
    def test_database_enabled_not_shared_requires_database_volume_argument(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = False

        with self.assertRaises(AnsibleFilterError):
            compose_volumes(apps, "app")

    def test_database_enabled_not_shared_uses_database_volume_argument(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = False

        rendered = compose_volumes(apps, "app", database_volume="my_db_vol")
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["database"]["name"], "my_db_vol")

    def test_database_enabled_shared_true_does_not_add_database_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = True

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("database", data["volumes"])

    def test_database_enabled_shared_null_treated_as_not_shared(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = None

        rendered = compose_volumes(apps, "app", database_volume="my_db_vol")
        data = self._parse_yaml(rendered)

        self.assertIn("database", data["volumes"])
        self.assertEqual(data["volumes"]["database"]["name"], "my_db_vol")

    # -----------------------------
    # Redis volume
    # -----------------------------
    def test_redis_enabled_adds_redis_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = True

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_oauth2_enabled_adds_redis_volume_when_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["oauth2"]["enabled"] = True

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_oauth2_null_does_not_add_redis_if_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["oauth2"]["enabled"] = None

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("redis", data["volumes"])

    # -----------------------------
    # Extra volumes merge / override
    # -----------------------------
    def test_extra_volumes_are_added(self):
        apps = self._base_apps()

        rendered = compose_volumes(
            apps,
            "app",
            extra_volumes={"data": {"name": "pg_data_vol"}},
        )
        data = self._parse_yaml(rendered)

        self.assertIn("data", data["volumes"])
        self.assertEqual(data["volumes"]["data"]["name"], "pg_data_vol")

    def test_extra_volumes_override_auto(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = True

        rendered = compose_volumes(
            apps,
            "app",
            extra_volumes={"redis": {"name": "custom_redis"}},
        )
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["redis"]["name"], "custom_redis")

    def test_database_enabled_not_shared_without_database_volume_raises(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = False
        with self.assertRaises(AnsibleFilterError):
            compose_volumes(apps, "app", database_volume=None)

    def test_extra_volume_with_none_name_serializes_to_null(self):
        apps = self._base_apps()

        rendered = compose_volumes(
            apps,
            "app",
            extra_volumes={"data": {"name": None}},
        )
        data = self._parse_yaml(rendered)

        self.assertIsNone(data["volumes"]["data"]["name"])


if __name__ == "__main__":
    unittest.main()
