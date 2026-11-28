from __future__ import annotations

import importlib
import json
import runpy
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_fake_frappe = importlib.import_module(
    "tests.unit.python.roles.web-app-erpnext.files.apply._fake_frappe"
)
FakeFrappe = _fake_frappe.FakeFrappe
run_script = _fake_frappe.run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/login/rbac.py"
ROLE_VARS = PROJECT_ROOT / "roles/web-app-erpnext" / ROLE_FILE_VARS_MAIN
APP = "infinito_rbac"
SETTINGS = {
    "groups_claim": "groups",
    "username_claim": "preferred_username",
    "given_name_claim": "given_name",
    "family_name_claim": "family_name",
    "role_grants": {"/roles/web-app-erpnext/administrator": ["System Manager"]},
    "group_roles": {},
    "protected_users": ["Administrator", "Guest"],
    "protected_owners": {},
    "directory_provider": "directory",
    "uuid_attribute": "entryUUID",
    "directory_ids": True,
}


class InstallerFrappe(FakeFrappe):
    """The fake site plus its installed apps, its site config and the installer."""

    def __init__(self, installed, conf):
        super().__init__()
        self.installed = list(installed)
        self.conf = dict(conf)

    def get_installed_apps(self):
        return list(self.installed)

    def _install_app(self, name):
        self.calls.append(("install_app", name))
        self.installed.append(name)

    def _update_site_config(self, key, value):
        self.calls.append(("update_site_config", key))
        self.conf[key] = json.loads(json.dumps(value))

    def modules(self):
        installer = ModuleType("frappe.installer")
        installer.install_app = self._install_app
        installer.update_site_config = self._update_site_config
        return {**super().modules(), "frappe.installer": installer}


def _env(settings):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "LOGIN_RBAC_APP": APP,
        "LOGIN_RBAC_SETTINGS_JSON": json.dumps(settings),
    }


class TestLoginRbac(unittest.TestCase):
    def _run(self, frappe, settings=SETTINGS):
        return run_script(SCRIPT, frappe, _env(settings)).splitlines()

    def test_installs_the_app_and_writes_its_settings_on_a_fresh_site(self) -> None:
        frappe = InstallerFrappe(["frappe", "erpnext"], {})

        output = self._run(frappe)

        self.assertEqual(
            output, [f"CHANGED installed {APP}", f"CHANGED settings {APP}"]
        )
        self.assertEqual(frappe.installed, ["frappe", "erpnext", APP])
        self.assertEqual(frappe.conf[APP], SETTINGS)
        self.assertTrue(frappe.db.committed)

    def test_changes_nothing_once_installed_and_configured(self) -> None:
        frappe = InstallerFrappe(["frappe", "erpnext", APP], {APP: SETTINGS})

        self.assertEqual(self._run(frappe), ["UNCHANGED"])
        self.assertNotIn(("install_app", APP), frappe.calls)

    def test_rewrites_changed_settings_without_reinstalling(self) -> None:
        frappe = InstallerFrappe(
            ["frappe", "erpnext", APP], {APP: {**SETTINGS, "groups_claim": "roles"}}
        )

        self.assertEqual(self._run(frappe), [f"CHANGED settings {APP}"])
        self.assertEqual(frappe.conf[APP], SETTINGS)
        self.assertNotIn(("install_app", APP), frappe.calls)

    def test_turning_ldap_off_disables_the_ldap_settings_a_former_deploy_left(
        self,
    ) -> None:
        for directory_ids in (False, True):
            with self.subTest(directory_ids=directory_ids):
                frappe = InstallerFrappe(["frappe", "erpnext", APP], {APP: SETTINGS})
                frappe.singles["LDAP Settings"] = {
                    "enabled": 1,
                    "ldap_server_url": "ldap://openldap:389",
                }
                settings = {**SETTINGS, "directory_ids": directory_ids}

                first = self._run(frappe, settings)
                second = self._run(frappe, settings)

                self.assertEqual(
                    first,
                    ["UNCHANGED"]
                    if directory_ids
                    else [f"CHANGED settings {APP}", "CHANGED disabled LDAP Settings"],
                )
                self.assertEqual(second, ["UNCHANGED"])
                self.assertEqual(
                    frappe.singles["LDAP Settings"]["enabled"], int(directory_ids)
                )
                self.assertEqual(frappe.conf[APP]["directory_ids"], directory_ids)

    def test_the_site_is_connected_before_and_released_after_the_change(self) -> None:
        frappe = InstallerFrappe(["frappe"], {})

        self._run(frappe)

        self.assertEqual(
            frappe.calls,
            [
                (
                    "init",
                    "next.erp.infinito.example",
                    "/home/frappe/frappe-bench/sites",
                ),
                ("connect",),
                ("install_app", APP),
                ("update_site_config", APP),
                ("clear_cache",),
                ("destroy",),
            ],
        )

    def test_an_unchanged_site_still_drops_the_cached_hooks(self) -> None:
        frappe = InstallerFrappe(["frappe", "erpnext", APP], {APP: SETTINGS})

        self.assertEqual(self._run(frappe), ["UNCHANGED"])
        self.assertIn(("clear_cache",), frappe.calls)

    def test_settings_missing_a_key_fail_before_touching_the_site(self) -> None:
        frappe = InstallerFrappe(["frappe"], {})
        incomplete = {
            key: value for key, value in SETTINGS.items() if key != "protected_users"
        }

        with self.assertRaisesRegex(ValueError, "LOGIN_RBAC_SETTINGS_JSON"):
            self._run(frappe, incomplete)

        self.assertEqual(frappe.calls, [])

    def test_the_role_declares_exactly_the_settings_the_script_accepts(self) -> None:
        declared = load_yaml(str(ROLE_VARS))["ERPNEXT_LOGIN_RBAC_SETTINGS"]
        with patch.dict(sys.modules, InstallerFrappe([], {}).modules()):
            accepted = runpy.run_path(str(SCRIPT), run_name="rbac")["SETTINGS"]

        self.assertEqual(sorted(declared), sorted(accepted))

    def test_settings_without_the_directory_provider_fail_before_touching_the_site(
        self,
    ) -> None:
        frappe = InstallerFrappe(["frappe"], {})
        incomplete = {
            key: value for key, value in SETTINGS.items() if key != "directory_provider"
        }

        with self.assertRaisesRegex(ValueError, "directory_provider"):
            self._run(frappe, incomplete)

        self.assertEqual(frappe.calls, [])

    def test_settings_with_an_unknown_key_fail_before_touching_the_site(self) -> None:
        frappe = InstallerFrappe(["frappe"], {})

        with self.assertRaisesRegex(ValueError, "LOGIN_RBAC_SETTINGS_JSON"):
            self._run(frappe, {**SETTINGS, "extra": True})

        self.assertEqual(frappe.calls, [])

    def test_a_missing_app_name_fails_before_touching_the_site(self) -> None:
        frappe = InstallerFrappe(["frappe"], {})
        env = _env(SETTINGS)
        del env["LOGIN_RBAC_APP"]

        with self.assertRaises(KeyError):
            run_script(SCRIPT, frappe, env)

        self.assertEqual(frappe.calls, [])


if __name__ == "__main__":
    unittest.main()
