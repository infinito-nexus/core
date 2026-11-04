from __future__ import annotations

import runpy
import sys
import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from . import APP_PACKAGE
from ._fake_frappe import FakeFrappe

HOOKS = runpy.run_path(str(APP_PACKAGE / "hooks.py"))
UPSTREAM = "frappe.integrations.oauth2_logins"
KEYCLOAK_CALLBACKS = (f"{UPSTREAM}.login_via_keycloak", f"{UPSTREAM}.custom")


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
            sorted(KEYCLOAK_CALLBACKS),
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

    def test_the_module_listed_in_modules_txt_exists_as_a_package(self) -> None:
        modules = read_text(str(APP_PACKAGE / "modules.txt")).split()
        module = "_".join(modules).lower()

        self.assertTrue((APP_PACKAGE / module / "__init__.py").is_file(), module)


if __name__ == "__main__":
    unittest.main()
