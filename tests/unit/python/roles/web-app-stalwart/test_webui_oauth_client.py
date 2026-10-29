"""The OAuth client the WebUI signs in with when Stalwart is the authorization server.

The WebUI Application always names ``stalwart-webui`` as its client id, so
Stalwart resolves it against a registered ``x:OAuthClient``. That client's
redirect URIs must be the WebUI's own ``<origin>/<prefix>/oauth/callback`` for
every URL prefix, also for a plaintext onion origin, and it must be first-party
or its tokens cannot reach the management API. A deploy updates the client only
when it differs from that target.
"""

from __future__ import annotations

import json
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
TASK = ROLE / "tasks" / "02_webadmin.yml"
JMAP = ROLE / "templates" / "jmap" / "oauth_client"

CLIENT_ID = "stalwart-webui"
ONION = "http://mail.abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwx.onion"
CLEARNET = "https://mail.example.test"
PREFIXES = ["/admin", "/account"]


def _render(template: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _client(base_url: str, prefixes: list[str]) -> dict:
    rendered = _render(
        read_text(JMAP / "webui.json.j2"),
        STALWART_WEBUI_OAUTH_CLIENT_ID=CLIENT_ID,
        STALWART_WEBUI_APP_DESCRIPTION="Stalwart Web Interface",
        STALWART_WEBUI_BASE_URL=base_url,
        stalwart_webui_url_prefixes=prefixes,
    )
    return json.loads(rendered)


def _task(name_fragment: str) -> dict:
    tasks = load_yaml_any(str(TASK), default_if_missing=[])
    return next(t for t in tasks if name_fragment in t.get("name", ""))


def _updates(live: dict, desired: dict) -> bool:
    variables = {
        "stalwart_webui_oauth_clients": [live],
        "stalwart_webui_oauth_client": desired,
    }
    return all(
        _render("{{ (" + condition + ") | bool }}", **variables)
        for condition in _task("Align the WebUI OAuth client")["when"]
    )


class TestWebuiClientRedirectUris(unittest.TestCase):
    def test_an_onion_origin_registers_plaintext_callbacks(self):
        client = _client(ONION, PREFIXES)
        self.assertEqual(
            sorted(client["redirectUris"]),
            [f"{ONION}/account/oauth/callback", f"{ONION}/admin/oauth/callback"],
        )

    def test_a_clearnet_origin_registers_tls_callbacks(self):
        client = _client(CLEARNET, PREFIXES)
        self.assertEqual(
            sorted(client["redirectUris"]),
            [f"{CLEARNET}/account/oauth/callback", f"{CLEARNET}/admin/oauth/callback"],
        )

    def test_prefix_slashes_do_not_leak_into_the_uri(self):
        client = _client(ONION, ["admin/", "//account"])
        self.assertEqual(
            sorted(client["redirectUris"]),
            [f"{ONION}/account/oauth/callback", f"{ONION}/admin/oauth/callback"],
        )

    def test_logout_returns_to_the_login_page_of_each_prefix(self):
        client = _client(ONION, PREFIXES)
        self.assertEqual(
            sorted(client["postLogoutRedirectUris"]),
            [f"{ONION}/account/login", f"{ONION}/admin/login"],
        )

    def test_a_single_prefix_still_renders_valid_json(self):
        client = _client(ONION, ["/account"])
        self.assertEqual(
            client["redirectUris"], {f"{ONION}/account/oauth/callback": True}
        )


class TestWebuiClientIsAFirstPartyPublicClient(unittest.TestCase):
    def setUp(self):
        self.client = _client(ONION, PREFIXES)

    def test_it_carries_the_application_client_id(self):
        self.assertEqual(self.client["clientId"], CLIENT_ID)

    def test_it_is_first_party(self):
        self.assertIs(self.client["firstParty"], True)

    def test_it_has_no_secret(self):
        self.assertNotIn("secret", self.client)

    def test_it_allows_the_code_and_refresh_grants(self):
        self.assertEqual(
            self.client["grantTypes"],
            {"authorizationCode": True, "refreshToken": True},
        )


class TestWebuiClientJmapBodies(unittest.TestCase):
    def setUp(self):
        self.client = _client(ONION, PREFIXES)

    def test_create_registers_the_client(self):
        body = json.loads(
            _render(
                read_text(JMAP / "create.json.j2"),
                stalwart_webui_oauth_client=self.client,
            )
        )
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:OAuthClient/set")
        self.assertEqual(list(args["create"].values()), [self.client])

    def test_update_patches_the_registered_record(self):
        body = json.loads(
            _render(
                read_text(JMAP / "update.json.j2"),
                stalwart_webui_oauth_client=self.client,
                stalwart_webui_oauth_clients=[{"id": "b7", "clientId": CLIENT_ID}],
            )
        )
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:OAuthClient/set")
        self.assertEqual(args["update"], {"b7": self.client})

    def test_get_lists_every_client(self):
        body = json.loads(read_text(JMAP / "get.json.j2"))
        method, args, _tag = body["methodCalls"][0]
        self.assertEqual(method, "x:OAuthClient/get")
        self.assertIsNone(args["ids"])


class TestWebuiClientIsUpdatedOnlyOnDrift(unittest.TestCase):
    def setUp(self):
        self.desired = _client(ONION, PREFIXES)
        self.live = {
            **self.desired,
            "id": "b7",
            "createdAt": "2026-10-27T10:00:00Z",
            "expiresAt": None,
            "contacts": {},
            "logo": None,
            "scopes": {},
        }

    def test_a_matching_client_is_left_alone(self):
        self.assertFalse(_updates(self.live, self.desired))

    def test_a_client_for_another_origin_is_updated(self):
        live = {
            **self.live,
            "redirectUris": _client(CLEARNET, PREFIXES)["redirectUris"],
        }
        self.assertTrue(_updates(live, self.desired))

    def test_a_client_missing_a_logout_target_is_updated(self):
        live = {**self.live, "postLogoutRedirectUris": {}}
        self.assertTrue(_updates(live, self.desired))

    def test_a_third_party_client_is_updated(self):
        live = {**self.live, "firstParty": False}
        self.assertTrue(_updates(live, self.desired))


class TestApplicationNamesTheClientUnconditionally(unittest.TestCase):
    def _oauth_client_id(self, sso_enabled: bool) -> str:
        task = _task("Point the WebUI Application")
        body = json.loads(
            _render(
                task["vars"]["stalwart_jmap_body"],
                stalwart_webui_app_id="a1",
                STALWART_WEBUI_LOCAL_URL="file:///etc/stalwart/webui.zip",
                STALWART_WEBUI_OAUTH_CLIENT_ID=CLIENT_ID,
                STALWART_SSO_ENABLED=sso_enabled,
            )
        )
        return body["methodCalls"][0][1]["update"]["a1"]["oauthClientId"]

    def test_with_sso(self):
        self.assertEqual(self._oauth_client_id(True), CLIENT_ID)

    def test_without_sso(self):
        self.assertEqual(self._oauth_client_id(False), CLIENT_ID)


if __name__ == "__main__":
    unittest.main()
