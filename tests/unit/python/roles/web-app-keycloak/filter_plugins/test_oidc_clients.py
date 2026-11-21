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


def _client(url):
    return {"clientId": "x", "attributes": {"backchannel.logout.url": url}}


def _app_with_roles(clients, client_roles):
    app = _app(clients)
    app["services"]["sso"]["oidc"]["client_roles"] = client_roles
    return app


class TestDeclaredClientRoleGrants(unittest.TestCase):
    def setUp(self):
        self.grants = _load().kc_declared_client_role_grants

    def test_a_declared_client_role_is_granted_to_the_rbac_group(self):
        apps = {
            "web-app-nextcloud": _app_with_roles(
                {"user_oidc": "nextcloud-user-oidc"},
                {"user_oidc": {"admin": "administrator"}},
            )
        }
        self.assertEqual(
            self.grants(apps, ["web-app-nextcloud"], "roles"),
            [
                {
                    "client_id": "nextcloud-user-oidc",
                    "role": "admin",
                    "group_path": "/roles/web-app-nextcloud/administrator",
                }
            ],
        )

    def test_a_client_absent_in_this_mode_grants_nothing(self):
        apps = {
            "web-app-nextcloud": _app_with_roles(
                {}, {"user_oidc": {"admin": "administrator"}}
            )
        }
        self.assertEqual(self.grants(apps, ["web-app-nextcloud"], "roles"), [])

    def test_an_app_outside_the_run_grants_nothing(self):
        apps = {
            "web-app-nextcloud": _app_with_roles(
                {"user_oidc": "nextcloud-user-oidc"},
                {"user_oidc": {"admin": "administrator"}},
            )
        }
        self.assertEqual(self.grants(apps, ["web-app-other"], "roles"), [])

    def test_the_group_root_is_normalized(self):
        apps = {"web-app-x": _app_with_roles({"a": "x-a"}, {"a": {"r": "editor"}})}
        (grant,) = self.grants(apps, ["web-app-x"], "/roles/")
        self.assertEqual(grant["group_path"], "/roles/web-app-x/editor")

    def test_malformed_declarations_are_survivable(self):
        self.assertEqual(self.grants(None, ["web-app-x"], "roles"), [])
        apps = {"web-app-x": _app_with_roles({"a": "x-a"}, {"a": ["admin"]})}
        self.assertEqual(self.grants(apps, ["web-app-x"], "roles"), [])


class TestBackchannelLogoutUrls(unittest.TestCase):
    def setUp(self):
        self.urls = _load().kc_backchannel_logout_urls

    def test_every_receiving_client_contributes_its_url_once(self):
        url = "http://matrix.example.onion/_synapse/client/oidc/backchannel_logout"
        self.assertEqual(self.urls([_client(url), _client(url)]), [url])

    def test_a_client_without_a_receiver_contributes_nothing(self):
        clients = [
            {"clientId": "shared", "attributes": {"frontchannel.logout.url": "x"}},
            {"clientId": "bare"},
            _client("  "),
        ]
        self.assertEqual(self.urls(clients), [])

    def test_a_malformed_client_list_is_survivable(self):
        self.assertEqual(self.urls(None), [])
        self.assertEqual(self.urls(["not-a-client", {"attributes": "x"}]), [])


def _gated(client, *, flavor="oauth2", enabled=True):
    """
    Args:
        client: the ``services.sso.oauth2.client`` value, None for none.
        flavor: ``services.sso.flavor``.
        enabled: ``services.sso.enabled``.

    Returns:
        One application config with that SSO block.
    """
    oauth2 = {"origin": {"host": "app", "port": "8000"}}
    if client is not None:
        oauth2["client"] = client
    return {
        "services": {"sso": {"enabled": enabled, "flavor": flavor, "oauth2": oauth2}}
    }


class TestProxyClients(unittest.TestCase):
    def setUp(self):
        self.clients = _load().kc_proxy_clients
        self.own = {"id": "x-gate", "scopes": ["kc-admin-api"]}

    def test_a_gated_app_with_its_own_client_yields_one_record(self):
        apps = {"web-app-x": _gated(self.own), "web-app-y": _gated(None)}
        self.assertEqual(
            self.clients(apps, ["web-app-y", "web-app-x"]),
            [
                {
                    "application_id": "web-app-x",
                    "client_id": "x-gate",
                    "scopes": ["kc-admin-api"],
                }
            ],
        )

    def test_negative_control_no_record_without_gate_or_deployment(self):
        for apps, app_ids in (
            ({"web-app-x": _gated(None)}, ["web-app-x"]),
            ({"web-app-x": _gated(self.own, flavor="oidc")}, ["web-app-x"]),
            ({"web-app-x": _gated(self.own, enabled=False)}, ["web-app-x"]),
            ({"web-app-x": _gated(self.own)}, ["web-app-y"]),
            ({"web-app-x": _gated(self.own)}, []),
            (None, ["web-app-x"]),
        ):
            with self.subTest(apps=apps, app_ids=app_ids):
                self.assertEqual(self.clients(apps, app_ids), [])

    def test_records_are_sorted_by_application(self):
        apps = {
            "web-app-b": _gated({"id": "b-gate", "scopes": []}),
            "web-app-a": _gated({"id": "a-gate", "scopes": []}),
        }
        self.assertEqual(
            [r["client_id"] for r in self.clients(apps, ["web-app-b", "web-app-a"])],
            ["a-gate", "b-gate"],
        )

    def test_a_client_without_scopes_fails_loudly(self):
        apps = {"web-app-x": _gated({"id": "x-gate"})}
        with self.assertRaises(ValueError):
            self.clients(apps, ["web-app-x"])


if __name__ == "__main__":
    unittest.main()
