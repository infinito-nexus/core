# tests/unit/cli/create/inventory/test_services_disabler.py
from __future__ import annotations

import os
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml import YAML

from cli.create.inventory.services_disabler import (
    apply_services_disabled,
    apply_services_disabled_from_env,
    assert_services_disabled_inventory_consistency_from_env,
    find_provider_roles,
    find_services_disabled_conflicts,
    parse_services_disabled,
    remove_roles_from_inventory,
)


class TestParseServicesDisabled(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(parse_services_disabled("oidc ldap"), ["oidc", "ldap"])

    def test_comma_separated(self):
        self.assertEqual(parse_services_disabled("oidc,ldap"), ["oidc", "ldap"])

    def test_mixed(self):
        self.assertEqual(
            parse_services_disabled("oidc, ldap matomo"), ["oidc", "ldap", "matomo"]
        )

    def test_empty(self):
        self.assertEqual(parse_services_disabled(""), [])

    def test_whitespace_only(self):
        self.assertEqual(parse_services_disabled("   "), [])


class TestFindProviderRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.roles_dir = Path(self.tmp.name) / "roles"
        self.roles_dir.mkdir()

    def _make_role(self, role_name: str, services: dict) -> None:
        role_dir = self.roles_dir / role_name
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "vars").mkdir(parents=True)
        # New layout (req-008): meta/services.yml is the services map directly
        with (role_dir / "meta" / "services.yml").open("w") as f:
            import yaml

            yaml.dump(services, f)
        with (role_dir / "vars" / "main.yml").open("w") as f:
            import yaml

            yaml.dump({"application_id": role_name}, f)

    def test_finds_shared_provider_role(self):
        self._make_role(
            "web-app-matomo",
            {"matomo": {"image": "matomo", "shared": True}},
        )
        result = find_provider_roles(["matomo"], self.roles_dir)
        self.assertEqual(result, {"matomo": "web-app-matomo"})

    def test_resolves_provider_via_provides_alias(self):
        self._make_role(
            "web-app-mailu",
            {"mailu": {"image": "mailu", "shared": True, "provides": "email"}},
        )
        result = find_provider_roles(["email"], self.roles_dir)
        self.assertEqual(result, {"email": "web-app-mailu"})

    def test_ignores_service_that_is_not_shared_or_provides(self):
        self._make_role(
            "svc-db-openldap",
            {"ldap": {"enabled": True}},
        )
        result = find_provider_roles(["ldap"], self.roles_dir)
        self.assertEqual(result, {})

    def test_no_match(self):
        self._make_role("web-app-foo", {"foo": {"image": "foo", "shared": True}})
        result = find_provider_roles(["oidc"], self.roles_dir)
        self.assertEqual(result, {})

    def test_multiple_services(self):
        self._make_role(
            "web-app-matomo",
            {"matomo": {"image": "matomo", "shared": True}},
        )
        self._make_role(
            "web-app-dashboard",
            {"dashboard": {"image": "port-ui", "shared": True}},
        )
        result = find_provider_roles(["matomo", "dashboard"], self.roles_dir)
        self.assertEqual(
            result,
            {
                "matomo": "web-app-matomo",
                "dashboard": "web-app-dashboard",
            },
        )


class TestRemoveRolesFromInventory(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True
        self.inventory = self.root / "devices.yml"

    def _write(self, data: dict) -> None:
        with self.inventory.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _read(self) -> dict:
        with self.inventory.open("r") as f:
            return self.yaml_rt.load(f)

    def test_removes_existing_group(self):
        self._write(
            {
                "all": {
                    "children": {
                        "web-app-matomo": {"hosts": {"localhost": {}}},
                        "web-app-nextcloud": {"hosts": {"localhost": {}}},
                    }
                }
            }
        )
        remove_roles_from_inventory(self.inventory, ["web-app-matomo"])
        result = self._read()
        self.assertNotIn("web-app-matomo", result["all"]["children"])
        self.assertIn("web-app-nextcloud", result["all"]["children"])

    def test_skips_missing_group(self):
        self._write(
            {"all": {"children": {"web-app-nextcloud": {"hosts": {"localhost": {}}}}}}
        )
        remove_roles_from_inventory(
            self.inventory, ["web-app-matomo"]
        )  # must not raise
        result = self._read()
        self.assertIn("web-app-nextcloud", result["all"]["children"])

    def test_no_op_on_missing_file(self):
        remove_roles_from_inventory(self.root / "nonexistent.yml", ["web-app-matomo"])

    def test_no_op_on_empty_list(self):
        self._write({"all": {"children": {"web-app-foo": {}}}})
        remove_roles_from_inventory(self.inventory, [])
        result = self._read()
        self.assertIn("web-app-foo", result["all"]["children"])


class TestApplyServicesDisabled(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True
        self.host_vars = self.root / "host_vars.yml"
        self.inventory = self.root / "devices.yml"
        self.roles_dir = self.root / "roles"
        self.roles_dir.mkdir()

    def _write_host_vars(self, data: dict) -> None:
        with self.host_vars.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _read_host_vars(self) -> dict:
        with self.host_vars.open("r") as f:
            return self.yaml_rt.load(f)

    def _write_inventory(self, data: dict) -> None:
        with self.inventory.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _read_inventory(self) -> dict:
        with self.inventory.open("r") as f:
            return self.yaml_rt.load(f)

    def _make_role(self, role_name: str, services: dict) -> None:
        role_dir = self.roles_dir / role_name
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "vars").mkdir(parents=True)
        # New layout (req-008): meta/services.yml is the services map directly
        with (role_dir / "meta" / "services.yml").open("w") as f:
            import yaml

            yaml.dump(services, f)
        with (role_dir / "vars" / "main.yml").open("w") as f:
            import yaml

            yaml.dump({"application_id": role_name}, f)

    def test_disables_service_in_host_vars_and_removes_from_inventory(self):
        self._write_host_vars(
            {
                "applications": {
                    "web-app-nextcloud": {
                        "services": {"matomo": {"enabled": True, "shared": True}}
                    }
                }
            }
        )
        self._write_inventory(
            {
                "all": {
                    "children": {
                        "web-app-matomo": {"hosts": {"localhost": {}}},
                        "web-app-nextcloud": {"hosts": {"localhost": {}}},
                    }
                }
            }
        )
        self._make_role(
            "web-app-matomo", {"matomo": {"image": "matomo", "shared": True}}
        )
        self._make_role(
            "web-app-nextcloud", {"matomo": {"enabled": True, "shared": True}}
        )

        apply_services_disabled(
            self.host_vars,
            ["matomo"],
            inventory_file=self.inventory,
            roles_dir=self.roles_dir,
        )

        hv = self._read_host_vars()
        self.assertFalse(
            hv["applications"]["web-app-nextcloud"]["services"]["matomo"]["enabled"]
        )

        inv = self._read_inventory()
        self.assertNotIn("web-app-matomo", inv["all"]["children"])
        self.assertIn("web-app-nextcloud", inv["all"]["children"])

    def test_disables_matching_service(self):
        self._write_host_vars(
            {
                "applications": {
                    "web-app-nextcloud": {
                        "services": {
                            "oidc": {"enabled": True, "shared": True},
                            "mariadb": {"enabled": True, "shared": True},
                        }
                    }
                }
            }
        )
        self._make_role(
            "web-app-nextcloud", {"oidc": {"enabled": True, "shared": True}}
        )
        apply_services_disabled(self.host_vars, ["oidc"], roles_dir=self.roles_dir)
        result = self._read_host_vars()
        svc = result["applications"]["web-app-nextcloud"]["services"]
        self.assertFalse(svc["oidc"]["enabled"])
        self.assertFalse(svc["oidc"]["shared"])
        self.assertTrue(svc["mariadb"]["enabled"])

    def test_creates_missing_service_entry_when_role_defines_it(self):
        self._write_host_vars(
            {
                "applications": {
                    "web-app-matomo": {"services": {"matomo": {"enabled": True}}}
                }
            }
        )
        # role defines oidc in its config
        self._make_role("web-app-matomo", {"oidc": {"enabled": True, "shared": True}})
        apply_services_disabled(self.host_vars, ["oidc"], roles_dir=self.roles_dir)
        result = self._read_host_vars()
        # existing service untouched
        self.assertTrue(
            result["applications"]["web-app-matomo"]["services"]["matomo"]["enabled"]
        )
        # missing service entry is created with enabled/shared false
        oidc = result["applications"]["web-app-matomo"]["services"]["oidc"]
        self.assertFalse(oidc["enabled"])
        self.assertFalse(oidc["shared"])

    def test_skips_app_whose_role_does_not_define_service(self):
        self._write_host_vars(
            {
                "applications": {
                    "web-app-matomo": {"services": {"matomo": {"enabled": True}}}
                }
            }
        )
        # role does NOT define oidc
        self._make_role("web-app-matomo", {"matomo": {"image": "matomo"}})
        apply_services_disabled(self.host_vars, ["oidc"], roles_dir=self.roles_dir)
        result = self._read_host_vars()
        self.assertNotIn(
            "oidc",
            result["applications"]["web-app-matomo"]["services"],
        )

    def test_creates_compose_section_for_app_without_compose(self):
        self._write_host_vars(
            {
                "applications": {
                    "web-app-foo": {"credentials": {"password": "secret"}},
                }
            }
        )
        # role defines matomo — so compose section must be created
        self._make_role("web-app-foo", {"matomo": {"enabled": True, "shared": True}})
        apply_services_disabled(self.host_vars, ["matomo"], roles_dir=self.roles_dir)
        result = self._read_host_vars()
        svc = result["applications"]["web-app-foo"]["services"]["matomo"]
        self.assertFalse(svc["enabled"])
        self.assertFalse(svc["shared"])

    def test_creates_app_entry_when_not_in_host_vars(self):
        self._write_host_vars({"applications": {}})
        # role defines matomo but app is not yet in host_vars
        self._make_role("web-app-bar", {"matomo": {"enabled": True, "shared": True}})
        apply_services_disabled(self.host_vars, ["matomo"], roles_dir=self.roles_dir)
        result = self._read_host_vars()
        svc = result["applications"]["web-app-bar"]["services"]["matomo"]
        self.assertFalse(svc["enabled"])
        self.assertFalse(svc["shared"])

    def test_no_op_on_empty_list(self):
        self._write_host_vars({"applications": {}})
        apply_services_disabled(self.host_vars, [], roles_dir=self.roles_dir)
        self.assertEqual(self._read_host_vars(), {"applications": {}})

    def test_no_op_when_file_missing(self):
        apply_services_disabled(
            self.root / "nonexistent.yml", ["oidc"], roles_dir=self.roles_dir
        )

    def test_multiple_apps_and_services(self):
        self._write_host_vars(
            {
                "applications": {
                    "app-a": {"services": {"oidc": {"enabled": True, "shared": True}}},
                    "app-b": {"services": {"ldap": {"enabled": True, "shared": True}}},
                }
            }
        )
        self._make_role("app-a", {"oidc": {"enabled": True, "shared": True}})
        self._make_role("app-b", {"ldap": {"enabled": True, "shared": True}})
        apply_services_disabled(
            self.host_vars, ["oidc", "ldap"], roles_dir=self.roles_dir
        )
        result = self._read_host_vars()
        self.assertFalse(result["applications"]["app-a"]["services"]["oidc"]["enabled"])
        self.assertFalse(result["applications"]["app-b"]["services"]["ldap"]["enabled"])


class TestApplyServicesDisabledFromEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True
        self.host_vars = self.root / "host_vars.yml"
        self.roles_dir = self.root / "roles"
        self.roles_dir.mkdir()

    def _write(self, data: dict) -> None:
        with self.host_vars.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _read(self) -> dict:
        with self.host_vars.open("r") as f:
            return self.yaml_rt.load(f)

    def _make_role(self, role_name: str, services: dict) -> None:
        role_dir = self.roles_dir / role_name
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "vars").mkdir(parents=True)
        # New layout (req-008): meta/services.yml is the services map directly
        with (role_dir / "meta" / "services.yml").open("w") as f:
            import yaml

            yaml.dump(services, f)
        with (role_dir / "vars" / "main.yml").open("w") as f:
            import yaml

            yaml.dump({"application_id": role_name}, f)

    def test_reads_env_var(self):
        self._write(
            {
                "applications": {
                    "web-app-foo": {
                        "services": {"oidc": {"enabled": True, "shared": True}}
                    }
                }
            }
        )
        self._make_role("web-app-foo", {"oidc": {"enabled": True, "shared": True}})
        with unittest.mock.patch.dict(os.environ, {"SERVICES_DISABLED": "oidc"}):
            apply_services_disabled_from_env(self.host_vars, roles_dir=self.roles_dir)
        result = self._read()
        self.assertFalse(
            result["applications"]["web-app-foo"]["services"]["oidc"]["enabled"]
        )

    def test_no_op_when_env_not_set(self):
        self._write({"applications": {}})
        env = {k: v for k, v in os.environ.items() if k != "SERVICES_DISABLED"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            apply_services_disabled_from_env(self.host_vars, roles_dir=self.roles_dir)
        self.assertEqual(self._read(), {"applications": {}})


class TestServicesDisabledConflicts(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.roles_dir = self.root / "roles"
        self.roles_dir.mkdir()
        self.inventory_dir = self.root / "inventory"
        self.inventory_dir.mkdir()
        self.inventory_file = self.inventory_dir / "devices.yml"
        self.host_vars_dir = self.inventory_dir / "host_vars"
        self.host_vars_dir.mkdir()
        self.host_vars_file = self.host_vars_dir / "localhost.yml"
        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True

    def _make_role(self, role_name: str, services: dict) -> None:
        role_dir = self.roles_dir / role_name
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "vars").mkdir(parents=True)
        # New layout (req-008): meta/services.yml is the services map directly
        with (role_dir / "meta" / "services.yml").open("w") as f:
            import yaml

            yaml.dump(services, f)
        with (role_dir / "vars" / "main.yml").open("w") as f:
            import yaml

            yaml.dump({"application_id": role_name}, f)

    def _write_inventory(self, data: dict) -> None:
        with self.inventory_file.open("w") as f:
            self.yaml_rt.dump(data, f)

    def _write_host_vars(self, data: dict) -> None:
        with self.host_vars_file.open("w") as f:
            self.yaml_rt.dump(data, f)

    def test_reports_provider_role_conflict_for_provides_alias(self):
        self._make_role(
            "web-app-mailu",
            {"mailu": {"image": "mailu", "provides": "email", "shared": True}},
        )
        self._make_role(
            "web-app-fider",
            {"email": {"enabled": False, "shared": False}},
        )
        self._write_inventory(
            {
                "all": {
                    "children": {
                        "web-app-mailu": {"hosts": {"localhost": {}}},
                        "web-app-fider": {"hosts": {"localhost": {}}},
                    }
                }
            }
        )
        self._write_host_vars(
            {
                "applications": {
                    "web-app-fider": {
                        "services": {"email": {"enabled": False, "shared": False}}
                    }
                }
            }
        )

        conflicts = find_services_disabled_conflicts(
            inventory_dir=self.inventory_dir,
            services=["email"],
            roles_dir=self.roles_dir,
        )

        self.assertEqual(len(conflicts), 1)
        self.assertIn("provider role 'web-app-mailu'", conflicts[0])

    def test_reports_enabled_service_conflict_for_deployed_app(self):
        self._make_role(
            "web-app-fider",
            {"email": {"enabled": True, "shared": True}},
        )
        self._write_inventory(
            {"all": {"children": {"web-app-fider": {"hosts": {"localhost": {}}}}}}
        )
        self._write_host_vars(
            {
                "applications": {
                    "web-app-fider": {
                        "services": {"email": {"enabled": True, "shared": True}}
                    }
                }
            }
        )

        conflicts = find_services_disabled_conflicts(
            inventory_dir=self.inventory_dir,
            services=["email"],
            roles_dir=self.roles_dir,
        )

        self.assertEqual(len(conflicts), 1)
        self.assertIn("enabled=True, shared=True", conflicts[0])

    def test_assert_from_env_noops_when_inventory_is_consistent(self):
        self._make_role(
            "web-app-fider",
            {"email": {"enabled": False, "shared": False}},
        )
        self._write_inventory(
            {"all": {"children": {"web-app-fider": {"hosts": {"localhost": {}}}}}}
        )
        self._write_host_vars(
            {
                "applications": {
                    "web-app-fider": {
                        "services": {"email": {"enabled": False, "shared": False}}
                    }
                }
            }
        )

        with unittest.mock.patch.dict(os.environ, {"SERVICES_DISABLED": "email"}):
            assert_services_disabled_inventory_consistency_from_env(
                inventory_dir=self.inventory_dir,
                roles_dir=self.roles_dir,
            )


if __name__ == "__main__":
    unittest.main()
