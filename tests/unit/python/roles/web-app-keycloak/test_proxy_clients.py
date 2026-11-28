from __future__ import annotations

import copy
import importlib.util
import json
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_META_SERVICES

from .templates.test_consumer_clients import (
    LOGIN_CLIENT,
    admin_findings,
    audience_findings,
    clients_of,
)
from .templates.test_consumer_clients import client_id as consumer_client_id
from .templates.test_consumer_clients import origin as consumer_origin
from .templates.test_consumer_clients import realm as consumer_realm
from .templates.test_realm_import_json import (
    CONTEXT,
    PROJECT_ROOT,
    ROLE_DIR,
    ROLE_VARS,
    fake_lookup,
    render,
)
from .test_admin_api_scope import role_var

APP = "web-svc-access-request"
APP_DIR = PROJECT_ROOT / "roles" / APP
CLIENT = "access-request"
SCOPE = ROLE_VARS["KEYCLOAK_ADMIN_API_SCOPE"]
SECRET_PATH = "secrets.credentials.sso_proxy_client_secret"
SECRET = "b" * 64
ORIGIN = "https://access-request.example.com"
ONION = "http://access-request." + "c" * 56 + ".onion"
CALLBACK = "/oauth2/callback"
SHARED = CONTEXT["KEYCLOAK_CLIENT_ID"]


def kc_proxy_clients():
    """
    Returns:
        The ``kc_proxy_clients`` filter of web-app-keycloak.
    """
    spec = importlib.util.spec_from_file_location(
        "oidc_clients", ROLE_DIR / "filter_plugins/oidc_clients.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kc_proxy_clients


def applications() -> dict:
    """
    Returns:
        A payload holding the access-request service as its meta/services.yml ships it.
    """
    return {APP: {"services": load_yaml_any(str(APP_DIR / ROLE_FILE_META_SERVICES))}}


def answer(name, *args, **kwargs):
    """
    Args:
        name: the lookup plugin the template asked for.
        *args: its terms.
        **kwargs: its options.

    Returns:
        The service's origin on two networks and its own client secret, else the shared fake answer.
    """
    if name == "tls" and args[0] == APP:
        return ORIGIN
    if name == "network_urls" and args[0] == ORIGIN:
        return [ORIGIN, ONION]
    if name == "config" and args == (APP, SECRET_PATH):
        return SECRET
    return fake_lookup(name, *args, **kwargs)


def realm(proxy_clients: list[dict]) -> dict:
    """
    Args:
        proxy_clients: KEYCLOAK_PROXY_CLIENTS.

    Returns:
        The parsed realm import.
    """
    return json.loads(
        render([], overrides={"KEYCLOAK_PROXY_CLIENTS": proxy_clients}, answer=answer)
    )


def proxy_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps the access-request client from a confidential gate client on its own callback.
    """
    clients = clients_of(realm, CLIENT)
    if len(clients) != 1:
        return [f"{len(clients)} clients {CLIENT}"]
    client = clients[0]
    findings = [
        f"{field} is {client.get(field)!r}"
        for field, value in LOGIN_CLIENT.items()
        if client.get(field) is not value
    ]
    if client["redirectUris"] != [ORIGIN + CALLBACK, ONION + CALLBACK]:
        findings.append(f"redirectUris are {client['redirectUris']}")
    if client["webOrigins"] != [ORIGIN, ONION]:
        findings.append(f"webOrigins are {client['webOrigins']}")
    if client.get("secret") != SECRET:
        findings.append("secret is not the service's own credential")
    if SCOPE not in client["defaultClientScopes"]:
        findings.append(f"{SCOPE} is no default scope")
    findings.extend(audience_findings(realm, CLIENT))
    findings.extend(admin_findings(realm, CLIENT))
    return findings


def scope_carriers(realm: dict) -> set[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        The clientIds holding the Admin API scope as a default or optional scope.
    """
    return {
        client["clientId"]
        for client in realm["clients"]
        if SCOPE in client.get("defaultClientScopes", [])
        or SCOPE in client.get("optionalClientScopes", [])
    }


class TestAccessRequestDeclaration(unittest.TestCase):
    def test_the_service_owns_a_gate_client_with_the_admin_api_scope(self) -> None:
        self.assertEqual(
            kc_proxy_clients()(applications(), [APP]),
            [{"application_id": APP, "client_id": CLIENT, "scopes": [SCOPE]}],
        )

    def test_negative_control_an_undeployed_service_owns_no_client(self) -> None:
        self.assertEqual(kc_proxy_clients()(applications(), ["web-app-keycloak"]), [])

    def test_the_secret_is_a_sha256_credential_of_the_service(self) -> None:
        secrets = load_yaml_any(str(APP_DIR / ROLE_FILE_META_SECRETS))
        credential = secrets["credentials"][SECRET_PATH.rsplit(".", 1)[-1]]
        self.assertEqual(credential["algorithm"], "sha256")
        self.assertEqual(credential["validation"], "^[a-f0-9]{64}$")


class TestProxyClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm(kc_proxy_clients()(applications(), [APP]))

    def test_the_client_is_confidential_on_its_own_callback(self) -> None:
        self.assertEqual(proxy_findings(self.realm), [])

    def test_negative_control_the_check_catches_a_widened_client(self) -> None:
        for field, value in (
            ("publicClient", True),
            ("directAccessGrantsEnabled", True),
            ("redirectUris", [ORIGIN + "/*"]),
            ("defaultClientScopes", ["basic", "roles"]),
            ("protocolMappers", []),
            ("secret", CONTEXT["OIDC"]["CLIENT"]["SECRET"]),
        ):
            with self.subTest(field=field):
                planted = copy.deepcopy(self.realm)
                clients_of(planted, CLIENT)[0][field] = value
                self.assertTrue(proxy_findings(planted))

    def test_only_the_gate_client_carries_the_admin_api_scope(self) -> None:
        self.assertEqual(scope_carriers(self.realm), {CLIENT})
        self.assertNotIn(SHARED, scope_carriers(self.realm))

    def test_negative_control_without_a_declaration_no_client_carries_it(
        self,
    ) -> None:
        bare = realm([])
        self.assertEqual(clients_of(bare, CLIENT), [])
        self.assertEqual(scope_carriers(bare), set())

    def test_the_shared_client_keeps_its_scopes(self) -> None:
        self.assertEqual(
            clients_of(self.realm, SHARED)[0]["defaultClientScopes"],
            clients_of(realm([]), SHARED)[0]["defaultClientScopes"],
        )

    def test_consumer_clients_keep_their_wildcard_redirect(self) -> None:
        gitea = clients_of(consumer_realm(), consumer_client_id("web-app-gitea"))[0]
        self.assertEqual(
            gitea["redirectUris"], [consumer_origin("web-app-gitea") + "/*"]
        )


class TestProxyClientConverge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm(kc_proxy_clients()(applications(), [APP]))
        cls.ids = role_var(
            "KEYCLOAK_PROXY_CLIENT_IDS",
            KEYCLOAK_PROXY_CLIENTS=kc_proxy_clients()(applications(), [APP]),
        )

    def settings_ids(self, proxy_ids: list[str]) -> list[str]:
        """
        Args:
            proxy_ids: KEYCLOAK_PROXY_CLIENT_IDS.

        Returns:
            KEYCLOAK_SETTINGS_CLIENT_IDS, with no other declared client.
        """
        return role_var(
            "KEYCLOAK_SETTINGS_CLIENT_IDS",
            KEYCLOAK_CLIENT_ID=SHARED,
            KEYCLOAK_DECLARED_CLIENT_IDS=[],
            KEYCLOAK_PROXY_CLIENT_IDS=proxy_ids,
            KEYCLOAK_SAML_CLIENT_IDS=[],
            KEYCLOAK_WORKSPACE_CLIENT_IDS=[],
        )

    def test_the_proxy_client_ids_come_from_the_records(self) -> None:
        self.assertEqual(self.ids, [CLIENT])

    def test_the_settings_converge_creates_and_updates_the_client(self) -> None:
        self.assertEqual(self.settings_ids(self.ids), [SHARED, CLIENT])
        self.assertEqual(
            role_var(
                "KEYCLOAK_SETTINGS_MISSING_CLIENT_IDS",
                KEYCLOAK_SETTINGS_CLIENT_IDS=self.settings_ids(self.ids),
                KEYCLOAK_DICTIONARY_REALM=self.realm,
            ),
            [],
        )

    def test_negative_control_without_proxy_ids_the_converge_skips_it(self) -> None:
        self.assertEqual(self.settings_ids([]), [SHARED])

    def test_the_audience_mapper_converges_on_existing_realms(self) -> None:
        for proxy_ids, expected in ((self.ids, [CLIENT]), ([], [])):
            with self.subTest(proxy_ids=proxy_ids):
                self.assertEqual(
                    role_var(
                        "KEYCLOAK_DECLARED_MAPPER_CLIENT_IDS",
                        KEYCLOAK_DICTIONARY_REALM=self.realm,
                        KEYCLOAK_DECLARED_CLIENT_IDS=[],
                        KEYCLOAK_PROXY_CLIENT_IDS=proxy_ids,
                    ),
                    expected,
                )

    def test_the_realm_check_of_the_admin_api_scope_runs(self) -> None:
        self.assertEqual(
            role_var(
                "KEYCLOAK_ADMIN_API_CLIENT_IDS",
                KEYCLOAK_DICTIONARY_REALM=self.realm,
                KEYCLOAK_ADMIN_API_SCOPE=SCOPE,
            ),
            [CLIENT],
        )

    def test_the_records_follow_the_deployed_applications(self) -> None:
        environment = NativeEnvironment(undefined=StrictUndefined)
        environment.filters["kc_proxy_clients"] = kc_proxy_clients()
        template = environment.from_string(ROLE_VARS["KEYCLOAK_PROXY_CLIENTS"])
        for groups, expected in (
            ([APP], [{"application_id": APP, "client_id": CLIENT, "scopes": [SCOPE]}]),
            (["web-app-keycloak"], []),
        ):
            answers = {"applications": applications(), "deployment": {"groups": groups}}
            with self.subTest(groups=groups):
                self.assertEqual(
                    template.render(lookup=lambda name, answers=answers: answers[name]),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
