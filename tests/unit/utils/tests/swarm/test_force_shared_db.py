from __future__ import annotations

import os
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml import YAML

from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.tests.swarm.force_shared_db import (
    db_provider_service_keys,
    force_shared_true,
    main,
)


class TestDbProviderServiceKeys(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.roles_dir = Path(self.tmp.name) / "roles"
        self.roles_dir.mkdir()

    def _make_role(self, role_name: str, services: dict) -> None:
        role_dir = self.roles_dir / role_name
        (role_dir / "meta").mkdir(parents=True)
        dump_yaml(role_dir / ROLE_FILE_META_SERVICES, services)

    def test_collects_only_svc_db_provider_keys(self):
        self._make_role(
            "svc-db-mariadb", {"mariadb": {"shared": True, "enabled": True}}
        )
        self._make_role("svc-db-postgres", {"postgres": {"shared": True}})
        self._make_role("web-app-matomo", {"matomo": {"shared": True}})
        self.assertEqual(
            db_provider_service_keys(self.roles_dir), {"mariadb", "postgres"}
        )

    def test_ignores_entries_without_provider_markers(self):
        self._make_role("svc-db-foo", {"foo": {"lifecycle": "beta"}})
        self.assertEqual(db_provider_service_keys(self.roles_dir), set())

    def test_empty_roles_dir(self):
        self.assertEqual(db_provider_service_keys(self.roles_dir), set())


class TestForceSharedTrue(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host_vars = self.root / "host_vars.yml"
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True

    def _write(self, data: dict) -> None:
        with self.host_vars.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _read(self) -> dict:
        with self.host_vars.open("r") as f:
            return self.yaml_rt.load(f)

    def test_flips_shared_false_to_true_for_db_service_only(self):
        self._write(
            {
                "applications": {
                    "web-app-matomo": {
                        "services": {
                            "mariadb": {"enabled": True, "shared": False},
                            "matomo": {"enabled": True},
                        }
                    }
                }
            }
        )
        self.assertTrue(force_shared_true(self.host_vars, {"mariadb", "postgres"}))
        svc = self._read()["applications"]["web-app-matomo"]["services"]
        self.assertTrue(svc["mariadb"]["shared"])
        self.assertNotIn("shared", svc["matomo"])

    def test_no_change_when_already_shared(self):
        self._write(
            {"applications": {"a": {"services": {"mariadb": {"shared": True}}}}}
        )
        self.assertFalse(force_shared_true(self.host_vars, {"mariadb"}))

    def test_ignores_non_db_service(self):
        self._write({"applications": {"a": {"services": {"web": {"shared": False}}}}})
        self.assertFalse(force_shared_true(self.host_vars, {"mariadb"}))
        self.assertFalse(self._read()["applications"]["a"]["services"]["web"]["shared"])

    def test_multiple_apps_and_db_services(self):
        self._write(
            {
                "applications": {
                    "a": {"services": {"mariadb": {"shared": False}}},
                    "b": {"services": {"postgres": {"shared": False}}},
                }
            }
        )
        self.assertTrue(force_shared_true(self.host_vars, {"mariadb", "postgres"}))
        apps = self._read()["applications"]
        self.assertTrue(apps["a"]["services"]["mariadb"]["shared"])
        self.assertTrue(apps["b"]["services"]["postgres"]["shared"])

    def test_noop_on_missing_file(self):
        self.assertFalse(force_shared_true(self.root / "nope.yml", {"mariadb"}))

    def test_noop_when_app_has_no_services(self):
        self._write({"applications": {"a": {}}})
        self.assertFalse(force_shared_true(self.host_vars, {"mariadb"}))


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inv_dir = Path(self.tmp.name)
        self.host_vars_dir = self.inv_dir / "host_vars"
        self.host_vars_dir.mkdir()
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True

    def test_main_forces_shared_across_host_vars(self):
        hv = self.host_vars_dir / "localhost.yml"
        with hv.open("w") as f:
            self.yaml_rt.dump(
                {
                    "applications": {
                        "web-app-matomo": {
                            "services": {"mariadb": {"enabled": True, "shared": False}}
                        }
                    }
                },
                f,
            )
        with unittest.mock.patch.dict(os.environ, {"INV_DIR": str(self.inv_dir)}):
            self.assertEqual(main(), 0)
        with hv.open("r") as f:
            result = self.yaml_rt.load(f)
        self.assertTrue(
            result["applications"]["web-app-matomo"]["services"]["mariadb"]["shared"]
        )

    def test_main_noop_when_host_vars_dir_missing(self):
        missing = self.inv_dir / "sub"
        with unittest.mock.patch.dict(os.environ, {"INV_DIR": str(missing)}):
            self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
