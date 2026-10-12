"""Which Keycloak clients get converged, and — more importantly — which do not.

The realm import also carries Keycloak's own built-in clients (``account``,
``broker``, ``realm-management`` ...). Converging those would be wrong, so the
set is taken from what applications declare about themselves rather than from
the realm document. An application that declares nothing contributes nothing,
which is what keeps this a no-op for every app that needs only the one shared
client.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PLUGIN = (
    Path(__file__).parent
    / "../../../../../../roles/web-app-keycloak/filter_plugins/oidc_clients.py"
).resolve()


def _load():
    spec = importlib.util.spec_from_file_location("oidc_clients", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _app(clients):
    return {"services": {"sso": {"oidc": {"clients": clients}}}}


class TestDeclaredClientApps(unittest.TestCase):
    def setUp(self):
        self.apps = _load().kc_declared_client_apps

    def test_only_declaring_apps_are_listed(self):
        apps = {
            "web-app-stalwart": _app({"webui": "stalwart-webui"}),
            "web-app-nextcloud": {"services": {"sso": {"oidc": {}}}},
        }
        self.assertEqual(
            self.apps(apps, ["web-app-stalwart", "web-app-nextcloud"]),
            ["web-app-stalwart"],
        )

    def test_an_undeployed_app_is_not_listed(self):
        apps = {"web-app-stalwart": _app({"webui": "stalwart-webui"})}
        self.assertEqual(self.apps(apps, ["web-app-other"]), [])

    def test_a_malformed_map_is_survivable(self):
        self.assertEqual(self.apps(None, ["a"]), [])


class TestDeclaredClientIds(unittest.TestCase):
    def setUp(self):
        self.ids = _load().kc_declared_client_ids

    def test_an_application_contributes_the_clients_it_declares(self):
        apps = {
            "web-app-stalwart": _app(
                {"webui": "stalwart-webui", "webmail": "stalwart-webmail"}
            )
        }
        self.assertEqual(
            self.ids(apps, ["web-app-stalwart"]),
            ["stalwart-webmail", "stalwart-webui"],
        )

    def test_an_application_that_declares_nothing_contributes_nothing(self):
        apps = {"web-app-nextcloud": {"services": {"sso": {"oidc": {}}}}}
        self.assertEqual(self.ids(apps, ["web-app-nextcloud"]), [])

    def test_keycloak_builtins_are_never_included(self):
        """They live in the realm document, not in any application's declaration."""
        apps = {"web-app-stalwart": _app({"webui": "stalwart-webui"})}
        self.assertNotIn("account", self.ids(apps, ["web-app-stalwart"]))
        self.assertNotIn("realm-management", self.ids(apps, ["web-app-stalwart"]))

    def test_an_undeployed_application_is_not_consulted(self):
        apps = {
            "web-app-stalwart": _app({"webui": "stalwart-webui"}),
            "web-app-other": _app({"main": "other-client"}),
        }
        self.assertEqual(self.ids(apps, ["web-app-other"]), ["other-client"])

    def test_duplicate_declarations_collapse(self):
        apps = {
            "a": _app({"one": "shared-client"}),
            "b": _app({"two": "shared-client"}),
        }
        self.assertEqual(self.ids(apps, ["a", "b"]), ["shared-client"])

    def test_blank_and_non_string_declarations_are_ignored(self):
        apps = {"a": _app({"ok": "real", "blank": "  ", "wrong": 7, "none": None})}
        self.assertEqual(self.ids(apps, ["a"]), ["real"])

    def test_a_malformed_application_map_is_survivable(self):
        self.assertEqual(self.ids(None, ["a"]), [])
        self.assertEqual(self.ids({"a": "not-a-dict"}, ["a"]), [])

    def test_no_app_ids_means_every_application_in_the_map(self):
        apps = {"a": _app({"one": "client-a"}), "b": _app({"one": "client-b"})}
        self.assertEqual(self.ids(apps), ["client-a", "client-b"])


if __name__ == "__main__":
    unittest.main()
