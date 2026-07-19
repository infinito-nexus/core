from __future__ import annotations

import os
import sys
import unittest
from typing import Any
from unittest import mock

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

from plugins.filter.compose_volumes import compose_volumes  # noqa: E402
from utils.cache.yaml import load_yaml_str  # noqa: E402

_DIR_VAR_LIB = os.environ["INFINITO_DIR_VAR_LIB"]


def _call(applications: Any, application_id: str, **kwargs: Any) -> str:
    kwargs.setdefault("dir_var_lib", _DIR_VAR_LIB)
    return compose_volumes(applications, application_id, **kwargs)


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
            _call(None, "app")  # type: ignore[arg-type]

    def test_non_dict_applications_raises(self):
        with self.assertRaises(AnsibleFilterError):
            _call(["not-a-dict"], "app")  # type: ignore[arg-type]

    def test_empty_application_id_raises(self):
        apps = self._base_apps()
        with self.assertRaises(AnsibleFilterError):
            _call(apps, "")  # type: ignore[arg-type]

    def test_unknown_application_id_raises(self):
        apps = self._base_apps()
        with self.assertRaises(AnsibleFilterError):
            _call(apps, "missing-app")

    def test_renders_volumes_key_even_when_empty(self):
        apps = self._base_apps()
        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)
        self.assertEqual(data["volumes"], {})

    def test_database_enabled_not_shared_derives_database_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = False

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["database"]["name"], "app_database")

    def test_database_enabled_shared_true_does_not_add_database_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = True

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("database", data["volumes"])

    def test_database_enabled_shared_null_treated_as_not_shared(self):
        apps = self._base_apps()
        apps["app"]["services"]["mariadb"]["enabled"] = True
        apps["app"]["services"]["mariadb"]["shared"] = None

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("database", data["volumes"])
        self.assertEqual(data["volumes"]["database"]["name"], "app_database")

    def test_redis_enabled_adds_redis_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = True

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_sso_oauth2_flavor_enabled_adds_redis_volume_when_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = True

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("redis", data["volumes"])
        self.assertEqual(data["volumes"]["redis"]["name"], "app_redis")

    def test_sso_oidc_flavor_does_not_add_redis_if_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = True
        apps["app"]["services"]["sso"]["flavor"] = "oidc"

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("redis", data["volumes"])

    def test_sso_null_does_not_add_redis_if_redis_disabled(self):
        apps = self._base_apps()
        apps["app"]["services"]["redis"]["enabled"] = False
        apps["app"]["services"]["sso"]["enabled"] = None

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("redis", data["volumes"])

    def test_extra_volumes_are_added(self):
        apps = self._base_apps()

        rendered = _call(
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

        rendered = _call(
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

        rendered = _call(apps, "app")
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
            _call(apps, "app")

    def test_seaweedfs_enabled_not_shared_adds_seaweedfs_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": True, "shared": False}

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("seaweedfs", data["volumes"])
        self.assertEqual(data["volumes"]["seaweedfs"]["name"], "app_seaweedfs")

    def test_seaweedfs_enabled_shared_true_does_not_add_seaweedfs_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": True, "shared": True}

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertNotIn("seaweedfs", data["volumes"])

    def test_minio_enabled_not_shared_adds_minio_volume(self):
        apps = self._base_apps()
        apps["app"]["services"]["minio"] = {"enabled": True, "shared": False}

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("minio", data["volumes"])
        self.assertEqual(data["volumes"]["minio"]["name"], "app_minio")

    def test_objstore_engines_disabled_add_no_volumes(self):
        apps = self._base_apps()
        apps["app"]["services"]["seaweedfs"] = {"enabled": False, "shared": False}
        apps["app"]["services"]["minio"] = {"enabled": False, "shared": False}

        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"], {})

    def test_extra_volume_with_none_name_serializes_to_null(self):
        apps = self._base_apps()

        rendered = _call(
            apps,
            "app",
            extra_volumes={"data": {"name": None}},
        )
        data = self._parse_yaml(rendered)

        self.assertIsNone(data["volumes"]["data"]["name"])

    def test_swarm_nfs_opt_in_renders_driver_opts(self):
        apps = self._base_apps()
        rendered = _call(
            apps,
            "app",
            extra_volumes={"images": {"name": "app_images", "nfs": True}},
            deployment_mode="swarm",
            storage={
                "backend": "nfs",
                "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
            },
        )
        data = self._parse_yaml(rendered)

        vol = data["volumes"]["images"]
        self.assertEqual(vol["name"], "app_images")
        self.assertEqual(vol["driver"], "local")
        self.assertEqual(vol["driver_opts"]["type"], "none")
        self.assertEqual(vol["driver_opts"]["o"], "bind")
        self.assertEqual(vol["driver_opts"]["device"], f"{_DIR_VAR_LIB}/app_images")
        self.assertNotIn("nfs", vol)

    def test_swarm_nfs_false_opt_out_stays_plain_local_volume(self):
        apps = self._base_apps()
        rendered = _call(
            apps,
            "app",
            extra_volumes={
                "repositories": {"name": "app_repositories", "nfs": False},
                "shared": {"name": "app_shared"},
            },
            deployment_mode="swarm",
            storage={
                "backend": "nfs",
                "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
            },
        )
        data = self._parse_yaml(rendered)

        repositories = data["volumes"]["repositories"]
        self.assertEqual(repositories, {"name": "app_repositories"})
        shared = data["volumes"]["shared"]
        self.assertEqual(shared["driver"], "local")
        self.assertEqual(shared["driver_opts"]["device"], f"{_DIR_VAR_LIB}/app_shared")

    def test_swarm_nfs_false_opt_out_from_meta_volumes(self):
        apps = self._base_apps()
        apps["app"]["volumes"] = {
            "repositories": {
                "type": "volume",
                "name": "app_repositories",
                "nfs": False,
                "mounts": [{"service": "gitaly", "target": "/home/git/repositories"}],
            },
            "shared": {
                "type": "volume",
                "name": "app_shared",
                "mounts": [{"service": "web", "target": "/srv/app/shared"}],
            },
        }
        rendered = _call(
            apps,
            "app",
            deployment_mode="swarm",
            storage={
                "backend": "nfs",
                "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
            },
        )
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["repositories"], {"name": "app_repositories"})
        self.assertIn("driver_opts", data["volumes"]["shared"])

    def test_swarm_nfs_dict_value_keeps_rewrite(self):
        apps = self._base_apps()
        apps["app"]["volumes"] = {
            "data": {
                "type": "volume",
                "name": "app_data",
                "nfs": {"uid": 1000, "gid": 1000, "mode": "0750"},
                "mounts": [{"service": "web", "target": "/data"}],
            },
        }
        rendered = _call(
            apps,
            "app",
            deployment_mode="swarm",
            storage={
                "backend": "nfs",
                "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
            },
        )
        data = self._parse_yaml(rendered)

        vol = data["volumes"]["data"]
        self.assertEqual(vol["driver_opts"]["device"], f"{_DIR_VAR_LIB}/app_data")
        self.assertNotIn("nfs", vol)
        self.assertEqual(
            vol["x-infinito-nfs"], {"uid": 1000, "gid": 1000, "mode": "0750"}
        )

    def test_compose_mode_nfs_false_leaves_no_nfs_key(self):
        apps = self._base_apps()
        rendered = _call(
            apps,
            "app",
            extra_volumes={"repositories": {"name": "app_repositories", "nfs": False}},
            deployment_mode="compose",
            storage={"backend": "local"},
        )
        data = self._parse_yaml(rendered)

        self.assertEqual(data["volumes"]["repositories"], {"name": "app_repositories"})

    def test_swarm_pinned_role_stays_node_local(self):
        apps = self._base_apps()
        with mock.patch(
            "plugins.filter.compose_volumes.get_role_placement",
            return_value="manager",
        ):
            rendered = _call(
                apps,
                "app",
                extra_volumes={
                    "images": {"name": "app_images"},
                    "data": {"name": "app_data"},
                },
                deployment_mode="swarm",
                storage={
                    "backend": "nfs",
                    "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
                },
            )
        data = self._parse_yaml(rendered)

        self.assertNotIn("driver_opts", data["volumes"]["images"])
        self.assertNotIn("driver_opts", data["volumes"]["data"])

    def test_compose_mode_ignores_nfs_flag(self):
        apps = self._base_apps()
        rendered = _call(
            apps,
            "app",
            extra_volumes={"images": {"name": "app_images", "nfs": True}},
            deployment_mode="compose",
            storage={
                "backend": "nfs",
                "nfs": {"server": "10.0.0.20", "export_base": "/srv/nfs"},
            },
        )
        data = self._parse_yaml(rendered)

        self.assertNotIn("driver_opts", data["volumes"]["images"])
        self.assertNotIn("nfs", data["volumes"]["images"])

    def test_swarm_local_backend_ignores_nfs_flag(self):
        apps = self._base_apps()
        rendered = _call(
            apps,
            "app",
            extra_volumes={"images": {"name": "app_images", "nfs": True}},
            deployment_mode="swarm",
            storage={"backend": "local"},
        )
        data = self._parse_yaml(rendered)

        self.assertNotIn("driver_opts", data["volumes"]["images"])
        self.assertNotIn("nfs", data["volumes"]["images"])

    def test_config_with_all_mounts_gated_off_is_not_declared(self):
        apps = self._base_apps()
        apps["app"]["volumes"] = {
            "auth_ldap": {
                "type": "config",
                "source": "/opt/compose/app/volumes/auth_ldap.xml",
                "mounts": [
                    {
                        "service": "backend",
                        "target": "/etc/auth_ldap.xml",
                        "when": False,
                    }
                ],
            },
            "proxy_conf": {
                "type": "config",
                "source": "/opt/compose/app/volumes/default.conf",
                "mounts": [
                    {"service": "proxy", "target": "/etc/nginx/conf.d/default.conf"}
                ],
            },
        }
        rendered = _call(apps, "app")
        data = self._parse_yaml(rendered)

        self.assertIn("configs", data)
        self.assertNotIn("auth_ldap", data["configs"])
        self.assertIn("proxy_conf", data["configs"])


if __name__ == "__main__":
    unittest.main()
