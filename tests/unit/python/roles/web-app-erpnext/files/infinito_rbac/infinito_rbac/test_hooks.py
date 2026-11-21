from __future__ import annotations

import runpy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from utils.cache.files import read_text

from . import APP_PACKAGE
from ._fake_frappe import LDAP_SETTINGS_MODULE, FakeFrappe

HOOKS = runpy.run_path(str(APP_PACKAGE / "hooks.py"))
UPSTREAM = "frappe.integrations.oauth2_logins"
KEYCLOAK_CALLBACKS = (f"{UPSTREAM}.login_via_keycloak", f"{UPSTREAM}.custom")
DEFAULT_WRITER = "frappe.client.set_default"


class TestHooks(unittest.TestCase):
    def test_the_app_is_named_after_its_package(self) -> None:
        self.assertEqual(HOOKS["app_name"], APP_PACKAGE.name)
        self.assertEqual(APP_PACKAGE.parent.name, APP_PACKAGE.name)

    def test_frappe_finds_the_title_and_description_it_lists_for_every_app(
        self,
    ) -> None:
        for hook in ("app_title", "app_description", "app_publisher", "app_license"):
            self.assertIsInstance(HOOKS[hook], str, hook)
            self.assertTrue(HOOKS[hook].strip(), hook)

    def test_every_callback_that_completes_a_keycloak_sign_in_is_replaced(
        self,
    ) -> None:
        self.assertEqual(
            sorted(HOOKS["override_whitelisted_methods"]),
            sorted((*KEYCLOAK_CALLBACKS, DEFAULT_WRITER)),
            "Frappe's custom callback completes the sign-in of whichever Social Login "
            "Key its path names, so replacing login_via_keycloak alone leaves "
            "custom/keycloak as an unguarded way in",
        )

    def test_each_replacement_is_a_guest_endpoint_of_the_app(self) -> None:
        for upstream in KEYCLOAK_CALLBACKS:
            target = HOOKS["override_whitelisted_methods"][upstream]
            module, _, function = target.rpartition(".")
            package, _, name = module.partition(".")

            frappe = FakeFrappe()
            with patch.dict(sys.modules, frappe.modules()):
                loaded = runpy.run_path(
                    str(APP_PACKAGE / f"{name}.py"), run_name=module
                )

            self.assertEqual(package, HOOKS["app_name"], upstream)
            self.assertEqual(function, upstream.rpartition(".")[2], upstream)
            self.assertTrue(callable(loaded[function]), upstream)
            self.assertIs(frappe.whitelisted[function], True, upstream)

    def test_every_ldap_sign_in_runs_through_the_apps_controller(self) -> None:
        target = HOOKS["override_doctype_class"]["LDAP Settings"]
        module, _, name = target.rpartition(".")

        frappe = FakeFrappe()
        with patch.dict(sys.modules, frappe.modules()):
            loaded = runpy.run_path(
                str(APP_PACKAGE / f"{module.partition('.')[2]}.py"), run_name=module
            )
            upstream = sys.modules[LDAP_SETTINGS_MODULE].LDAPSettings

        self.assertEqual(module.partition(".")[0], HOOKS["app_name"])
        self.assertTrue(issubclass(loaded[name], upstream))
        self.assertIn("create_or_update_user", vars(loaded[name]))

    def test_deleting_an_account_drops_its_grant_records(self) -> None:
        target = HOOKS["doc_events"]["User"]["on_trash"]
        module, _, name = target.rpartition(".")
        package, _, shared = module.partition(".")

        frappe = FakeFrappe()
        frappe.record("alice@infinito.example", "Audit Editor")
        handler = getattr(frappe.modules()[module], name)
        handler(SimpleNamespace(name="alice@infinito.example"), "on_trash")

        self.assertEqual(package, HOOKS["app_name"])
        self.assertEqual(shared, "roles")
        self.assertEqual(frappe.default_rows, [])

    def test_renaming_an_account_carries_its_grant_and_id_records(self) -> None:
        target = HOOKS["doc_events"]["User"]["after_rename"]
        module, _, name = target.rpartition(".")
        old, new = "alice@infinito.example", "alice.new@infinito.example"
        uuid = "a11ce000-0000-4000-8000-000000000001"

        for merge in (False, True):
            with self.subTest(merge=merge):
                frappe = FakeFrappe()
                frappe.record(old, "Audit Editor")
                frappe.record_id(old, uuid)
                if merge:
                    frappe.record(new, "Audit Viewer")
                roles = frappe.modules()[module]
                handler = getattr(roles, name)
                handler(SimpleNamespace(name=new), "after_rename", old, new, merge)

                self.assertEqual(module.partition(".")[2], "roles")
                self.assertEqual(
                    (roles.mapped_grants(old), roles.recorded_ids(old)),
                    (set(), set()),
                )
                self.assertEqual(
                    roles.mapped_grants(new),
                    {"Audit Editor", "Audit Viewer"} if merge else {"Audit Editor"},
                )
                self.assertEqual(roles.recorded_ids(new), {uuid})

    def test_no_whitelisted_method_writes_defaults_of_an_arbitrary_parent(
        self,
    ) -> None:
        self.assertEqual(
            HOOKS["override_whitelisted_methods"][DEFAULT_WRITER],
            "infinito_rbac.login.refuse_default_write",
        )

    def test_the_module_listed_in_modules_txt_exists_as_a_package(self) -> None:
        modules = read_text(str(APP_PACKAGE / "modules.txt")).split()
        module = "_".join(modules).lower()

        self.assertTrue((APP_PACKAGE / module / "__init__.py").is_file(), module)


if __name__ == "__main__":
    unittest.main()
