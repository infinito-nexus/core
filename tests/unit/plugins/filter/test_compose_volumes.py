from __future__ import annotations

import sys
import unittest
from typing import Any

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

from plugins.filter.compose_volumes import compose_volumes  # noqa: E402
from utils.cache.yaml import load_yaml_str  # noqa: E402


class TestComposeVolumes(unittest.TestCase):
    def _parse_yaml(self, rendered: str) -> dict[str, Any]:
        self.assertIsInstance(rendered, str)
        data = load_yaml_str(rendered) if rendered.strip() else {}
        self.assertIsInstance(data, dict)
        self.assertIn("volumes", data)
        self.assertIsInstance(data["volumes"], dict)
        return data

    def _base_apps(self) -> dict[str, Any]:
        return {
            "app": {
                "services": {
                    "mariadb": {"enabled": False, "shared": False},
                    "redis": {"enabled": False},
                    "sso": {"enabled": False, "flavor": "oauth2"},
                }
            }
        }

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

    def test_renders_volumes_key_even_when_empty(self):
        apps = self._base_apps()
        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)
        self.assertEqual(data["volumes"], {})

    def test_database_enabled_not_shared_derives_database_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = False

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["database"]["name"], "app_database")

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

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("database", data["volumes"])
        self.assertEqual(data["volumes"]["database"]["name"], "app_database")

    def test_redis_enabled_adds_redis_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = True

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_sso_oauth2_flavor_enabled_adds_redis_volume_when_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = True

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_sso_oidc_flavor_does_not_add_redis_if_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = True
        apps["app"]["services"]["sso"]["flavor"] = "oidc"

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("redis", data["volumes"])

    def test_sso_null_does_not_add_redis_if_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = None

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("redis", data["volumes"])

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

    def test_database_enabled_not_shared_shared_provider_name_used_when_present(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = True
        apps["svc-db-mariadb"] = {"services": {"mariadb": {"name": "mariadb-central"}}}

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("database", data["volumes"])

    def test_database_simultaneous_postgres_and_mariadb_raises(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"] = {"enabled": True, "shared": False}
        apps["app"]["services"]["postgres"] = {"enabled": True, "shared": False}
        with self.assertRaisesRegex(
            AnsibleFilterError,
            "Simultaneous postgres \\+ mariadb",
        ):
            compose_volumes(apps, "app")

    def test_seaweedfs_enabled_not_shared_adds_seaweedfs_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": True, "shared": False}

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("seaweedfs", data["volumes"])
        self.assertEqual(data["volumes"]["seaweedfs"]["name"], "app_seaweedfs")

    def test_seaweedfs_enabled_shared_true_does_not_add_seaweedfs_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": True, "shared": True}

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("seaweedfs", data["volumes"])

    def test_minio_enabled_not_shared_adds_minio_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["minio"] = {"enabled": True, "shared": False}

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("minio", data["volumes"])
        self.assertEqual(data["volumes"]["minio"]["name"], "app_minio")

    def test_objstore_engines_disabled_add_no_volumes(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": False, "shared": False}
        apps["app"]["services"]["minio"] = {"enabled": False, "shared": False}

        rendered = compose_volumes(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"], {})

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
