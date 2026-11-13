from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_realm_import_json import (
    CLIENT_APPS,
    CONTEXT,
    REALM_MANAGEMENT,
    ROLE_DIR,
    ROLE_SERVICES,
    ROLE_VARS,
    realm_managing_service_accounts,
    render,
)

ON = {"KEYCLOAK_DIRECTORY_CLIENT_ENABLED": True}
REALM = CONTEXT["KEYCLOAK_REALM"]
CLIENT_ID = CONTEXT["KEYCLOAK_DIRECTORY_CLIENT_ID"]
SERVICE_ACCOUNT = CONTEXT["KEYCLOAK_DIRECTORY_SERVICE_ACCOUNT"]
STORE_ROLES = {"view-users", "query-users", "manage-users"}
LEAST_PRIVILEGE_CLIENT = {
    "publicClient": False,
    "clientAuthenticatorType": "client-secret",
    "serviceAccountsEnabled": True,
    "standardFlowEnabled": False,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "redirectUris": [],
    "webOrigins": [],
}
CLIENT_ID_REBUILT = re.compile(r"\}\}?-directory\b|['\"]-directory['\"]")
CLIENT_ID_DEFINITION = re.compile(r"^\s*KEYCLOAK_DIRECTORY_CLIENT_ID\s*:", re.MULTILINE)


def realm(overrides: dict | None = None) -> dict:
    """Parse the realm import with every client-declaring app.

    Args:
        overrides: context values replacing those of CONTEXT.
    """
    return json.loads(render([], client_apps=CLIENT_APPS, overrides=overrides))


def directory_clients(realm: dict) -> list[dict]:
    """Return the clients of ``realm`` that carry the directory client id.

    Args:
        realm: the parsed realm import.
    """
    return [client for client in realm["clients"] if client["clientId"] == CLIENT_ID]


def directory_users(realm: dict) -> list[dict]:
    """Return the users of ``realm`` that belong to the directory client.

    Args:
        realm: the parsed realm import.
    """
    return [
        user
        for user in realm["users"]
        if user["username"] == SERVICE_ACCOUNT
        or user.get("serviceAccountClientId") == CLIENT_ID
    ]


def client_findings(realm: dict) -> list[str]:
    """What keeps ``realm`` from holding exactly one least-privilege directory client.

    Args:
        realm: the parsed realm import.
    """
    clients = directory_clients(realm)
    if len(clients) != 1:
        return [f"{len(clients)} clients carry the id {CLIENT_ID}"]
    return [
        f"{field} is {clients[0].get(field)!r}"
        for field, value in LEAST_PRIVILEGE_CLIENT.items()
        if json.dumps(clients[0].get(field)) != json.dumps(value)
    ]


def drifted(value):
    """Return a value of the same JSON type that differs from ``value``.

    Args:
        value: a field value of LEAST_PRIVILEGE_CLIENT.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, list):
        return [*value, "*"]
    return f"{value}-drifted"


def resolve(name: str, config: dict):
    """Evaluate one expression of ``vars/main.yml`` against a role config.

    Args:
        name: the variable's name.
        config: the mapping ``lookup('config', application_id, <path>)`` walks.
    """

    def lookup(kind, _application_id, path):
        assert kind == "config", kind
        value = config
        for part in path.split("."):
            value = value[part]
        return value

    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    expression = ROLE_VARS[name].strip().removeprefix("{{").removesuffix("}}")
    return env.compile_expression(expression)(
        lookup=lookup, application_id="web-app-keycloak"
    )


class TestDirectoryClientSwitchOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm()

    def test_services_declare_the_switch_off(self) -> None:
        self.assertIs(ROLE_SERVICES["keycloak"]["directory_client"]["enabled"], False)

    def test_the_role_reads_the_switch_from_services(self) -> None:
        services = copy.deepcopy(ROLE_SERVICES)
        self.assertIs(
            resolve("KEYCLOAK_DIRECTORY_CLIENT_ENABLED", {"services": services}), False
        )
        services["keycloak"]["directory_client"]["enabled"] = True
        self.assertIs(
            resolve("KEYCLOAK_DIRECTORY_CLIENT_ENABLED", {"services": services}), True
        )

    def test_the_import_holds_neither_the_client_nor_its_service_account(self) -> None:
        self.assertEqual(directory_clients(self.realm), [])
        self.assertEqual(directory_users(self.realm), [])

    def test_the_absence_checks_find_the_switched_on_client(self) -> None:
        switched_on = realm(ON)
        self.assertEqual(len(directory_clients(switched_on)), 1)
        self.assertEqual(len(directory_users(switched_on)), 1)

    def test_the_field_check_fails_against_the_switch_off_render(self) -> None:
        self.assertEqual(
            client_findings(self.realm), [f"0 clients carry the id {CLIENT_ID}"]
        )


class TestDirectoryClientSwitchOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm(ON)

    def test_the_client_id_is_the_realm_with_a_directory_suffix(self) -> None:
        self.assertEqual(CLIENT_ID, f"{REALM}-directory")

    def test_the_import_holds_exactly_one_least_privilege_client(self) -> None:
        self.assertEqual(client_findings(self.realm), [])

    def test_the_field_check_catches_every_drifted_field(self) -> None:
        for field, value in LEAST_PRIVILEGE_CLIENT.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(self.realm)
                directory_clients(changed)[0][field] = drifted(value)
                self.assertEqual(len(client_findings(changed)), 1)

    def test_a_second_client_with_the_same_id_is_caught(self) -> None:
        doubled = copy.deepcopy(self.realm)
        doubled["clients"].append(copy.deepcopy(directory_clients(doubled)[0]))
        self.assertEqual(
            client_findings(doubled), [f"2 clients carry the id {CLIENT_ID}"]
        )

    def test_the_service_account_belongs_to_the_client(self) -> None:
        users = directory_users(self.realm)
        self.assertEqual(len(users), 1)
        user = users[0]
        self.assertEqual(user["username"], f"service-account-{CLIENT_ID}")
        self.assertEqual(user["serviceAccountClientId"], CLIENT_ID)
        self.assertEqual(user["realmRoles"], [f"default-roles-{REALM}"])
        self.assertEqual(user["groups"], [])

    def test_the_service_account_holds_exactly_the_three_user_roles(self) -> None:
        roles = directory_users(self.realm)[0]["clientRoles"]
        self.assertEqual(
            {client: set(names) for client, names in roles.items()},
            {REALM_MANAGEMENT: STORE_ROLES},
        )
        self.assertEqual(len(roles[REALM_MANAGEMENT]), len(STORE_ROLES))

    def test_only_the_directory_service_account_manages_the_realm(self) -> None:
        self.assertEqual(realm_managing_service_accounts(self.realm), [SERVICE_ACCOUNT])


class TestDirectoryClientCredential(unittest.TestCase):
    def setUp(self) -> None:
        secrets = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SECRETS))
        self.entry = secrets["credentials"]["directory_client_secret"]
        self.credential = hashlib.sha256(b"directory-client").hexdigest()

    def test_secrets_declare_a_sha256_credential(self) -> None:
        self.assertEqual(self.entry["algorithm"], "sha256")
        self.assertEqual(self.entry["validation"], "^[a-f0-9]{64}$")

    def test_the_validation_admits_a_lowercase_sha256_digest_only(self) -> None:
        pattern = re.compile(self.entry["validation"])
        self.assertTrue(pattern.fullmatch(self.credential))
        self.assertIsNone(pattern.fullmatch(self.credential.upper()))
        self.assertIsNone(pattern.fullmatch(self.credential[:40]))

    def test_the_rendered_client_carries_the_credential(self) -> None:
        config = {
            "secrets": {"credentials": {"directory_client_secret": self.credential}}
        }
        secret = resolve("KEYCLOAK_DIRECTORY_CLIENT_SECRET", config)
        rendered = realm({**ON, "KEYCLOAK_DIRECTORY_CLIENT_SECRET": secret})
        self.assertEqual(directory_clients(rendered)[0]["secret"], self.credential)


class TestDirectoryClientIdSpot(unittest.TestCase):
    def test_the_client_id_is_defined_once(self) -> None:
        candidates = {
            *PROJECT_ROOT.glob("roles/*/vars/*.yml"),
            *PROJECT_ROOT.glob("roles/*/defaults/*.yml"),
            *PROJECT_ROOT.glob("group_vars/**/*.yml"),
            *ROLE_DIR.rglob("*.yml"),
        }
        definitions = sorted(
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in candidates
            if CLIENT_ID_DEFINITION.search(read_text(str(path)))
        )
        self.assertEqual(
            definitions,
            [(ROLE_DIR / ROLE_FILE_VARS_MAIN).relative_to(PROJECT_ROOT).as_posix()],
        )

    def test_the_rebuild_check_catches_the_definition_itself(self) -> None:
        self.assertTrue(
            CLIENT_ID_REBUILT.search(ROLE_VARS["KEYCLOAK_DIRECTORY_CLIENT_ID"])
        )

    def test_no_consumer_rebuilds_the_client_id(self) -> None:
        definition = ROLE_DIR / ROLE_FILE_VARS_MAIN
        rebuilt = [
            path.relative_to(ROLE_DIR).as_posix()
            for path in ROLE_DIR.rglob("*")
            if path.is_file()
            and path != definition
            and path.suffix in {".yml", ".j2", ".js", ".py"}
            and CLIENT_ID_REBUILT.search(read_text(str(path)))
        ]
        self.assertEqual(rebuilt, [])


if __name__ == "__main__":
    unittest.main()
