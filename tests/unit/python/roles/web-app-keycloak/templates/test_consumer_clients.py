from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
)

from .test_realm_import_json import (
    CLIENT_APPS,
    EXPORT_CLIENT_SECRET,
    MEMBERS_CLIENT_SECRET,
    PROJECT_ROOT,
    REALM_MANAGEMENT,
    ROLE_DIR,
    ROLE_VARS,
    STORE_FIXTURE_CLIENT_SECRET,
    fake_lookup,
    organizations_context,
    render,
)

STORE = "web-app-cst-store"
SEMAPHORE_DIR = PROJECT_ROOT / "roles" / "web-app-semaphore"
STORE_FIXTURE = ROLE_VARS["KEYCLOAK_STORE_FIXTURE_CLIENT_ID"]
STORE_FRAGMENT = """\
{% from 'roles/web-app-keycloak/templates/import/clients/consumer.json.j2' import consumer_client with context %}
{{ consumer_client(
     application_id='web-app-cst-store',
     client_id=lookup('config', 'web-app-cst-store', 'services.sso.oidc.clients.web'),
     name='Store',
     secret=lookup('config', 'web-app-cst-store', 'secrets.credentials.oidc_client_secret'),
     login_url=true,
     audience=true,
     scopes=[KEYCLOAK_WORKSPACE_ROLES_SCOPE]) }}
"""
CONSUMERS = (STORE, "web-app-openbao", "web-app-semaphore", "web-app-gitea")
SCOPE = ROLE_VARS["KEYCLOAK_WORKSPACE_ROLES_SCOPE"]
MEMBERS_CLIENT = ROLE_VARS["KEYCLOAK_WORKSPACE_MEMBERS_CLIENT_ID"]
MEMBERS_ROLES = {"manage-organizations", "manage-users"}
EXPORT_CLIENT = "export"
EXPORT_ROLES = {"view-users", "view-organizations", "view-events"}
AUDIENCE_MAPPER = "oidc-audience-mapper"
LOGIN_CLIENT = {
    "publicClient": False,
    "standardFlowEnabled": True,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": False,
}
NO_FLOW = {
    "publicClient": False,
    "standardFlowEnabled": False,
    "implicitFlowEnabled": False,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": True,
}


def origin(application_id: str) -> str:
    """
    Args:
        application_id: the application.

    Returns:
        Its fixture origin.
    """
    return f"https://{application_id}.example.com"


def client_id(application_id: str) -> str:
    """
    Args:
        application_id: the application.

    Returns:
        The fixture client id it declares.
    """
    return f"{application_id}-web"


def answer(name, *args, **kwargs):
    """
    Args:
        name: the lookup plugin the template asked for.
        *args: its terms.
        **kwargs: its options.

    Returns:
        One origin, client id and secret per application, else the shared fake answer.
    """
    if name == "tls":
        return origin(args[0])
    if name == "network_urls":
        return [args[0]]
    if name == "config" and str(args[-1]) == "services.sso.oidc.clients.web":
        return client_id(args[0])
    if name == "config" and str(args[-1]) == "secrets.credentials.oidc_client_secret":
        return f"{args[0]}-secret"
    return fake_lookup(name, *args, **kwargs)


def realm(enabled: bool = True, invite_client_id: str | None = None) -> dict:
    """
    Args:
        enabled: the organizations switch.
        invite_client_id: the invite client id ``web-app-semaphore`` declares.

    Returns:
        The parsed realm import with every client-declaring app and the store's fragment.
    """
    with tempfile.TemporaryDirectory() as root:
        fragment = Path(root) / "roles" / STORE / "templates/keycloak/clients.json.j2"
        fragment.parent.mkdir(parents=True)
        fragment.write_text(STORE_FRAGMENT, encoding="utf-8")
        return json.loads(
            render(
                [],
                client_apps=[*CLIENT_APPS, STORE],
                overrides=organizations_context(enabled, invite_client_id),
                roots=[root],
                answer=answer,
            )
        )


def clients_of(realm: dict, wanted: str) -> list[dict]:
    """
    Args:
        realm: the parsed realm import.
        wanted: the client id.

    Returns:
        The clients of ``realm`` whose clientId is ``wanted``.
    """
    return [c for c in realm["clients"] if c["clientId"] == wanted]


def login_findings(realm: dict, application_id: str) -> list[str]:
    """
    Args:
        realm: the parsed realm import.
        application_id: the consumer.

    Returns:
        What keeps the consumer from its own confidential login client.
    """
    clients = clients_of(realm, client_id(application_id))
    if len(clients) != 1:
        return [f"{len(clients)} clients of {application_id}"]
    client = clients[0]
    findings = [
        f"{field} is {client.get(field)!r}"
        for field, value in LOGIN_CLIENT.items()
        if client.get(field) is not value
    ]
    own = origin(application_id)
    findings.extend(
        f"foreign redirect {uri}"
        for uri in client["redirectUris"]
        if not uri.startswith(own + "/")
    )
    findings.extend(
        f"foreign web origin {uri}" for uri in client["webOrigins"] if uri != own
    )
    if not client["redirectUris"]:
        findings.append("no redirect URI")
    if client.get("secret") != f"{application_id}-secret":
        findings.append("secret is not the consumer's own credential")
    return findings


def admin_findings(realm: dict, wanted: str) -> list[str]:
    """
    Args:
        realm: the parsed realm import.
        wanted: the client id.

    Returns:
        Every admin right ``realm`` gives that client.
    """
    findings = [
        "service account enabled"
        for c in clients_of(realm, wanted)
        if c.get("serviceAccountsEnabled")
    ]
    findings.extend(
        f"service account user {u['username']} with {sorted(u.get('clientRoles', {}))}"
        for u in realm["users"]
        if u.get("serviceAccountClientId") == wanted
    )
    findings.extend(
        f"scope mapping {m.get('roles')}"
        for mappings in realm.get("clientScopeMappings", {}).values()
        for m in mappings
        if m.get("client") == wanted
    )
    findings.extend(
        f"permission {p.get('name')}"
        for c in realm["clients"]
        for p in (c.get("authorizationSettings") or {}).get("policies", [])
        if wanted in json.dumps(p)
    )
    return findings


def audience_findings(realm: dict, wanted: str) -> list[str]:
    """
    Args:
        realm: the parsed realm import.
        wanted: the client id.

    Returns:
        What keeps that client from naming itself as audience exactly once.
    """
    client = clients_of(realm, wanted)[0]
    mappers = [
        m
        for m in client.get("protocolMappers", [])
        if m["protocolMapper"] == AUDIENCE_MAPPER
    ]
    if len(mappers) != 1:
        return [f"{len(mappers)} audience mappers"]
    config = mappers[0]["config"]
    return [
        f"{key} is {config.get(key)!r}"
        for key, value in (
            ("included.client.audience", wanted),
            ("access.token.claim", "true"),
        )
        if config.get(key) != value
    ]


def service_account_findings(
    realm: dict, wanted: str, roles: set[str], secret: str
) -> list[str]:
    """
    Args:
        realm: the parsed realm import.
        wanted: the client id.
        roles: the realm-management roles its service account holds, exactly.
        secret: the client secret its credential renders.

    Returns:
        What keeps that client from no flow, its secret and exactly ``roles``.
    """
    clients = clients_of(realm, wanted)
    if len(clients) != 1:
        return [f"{len(clients)} clients {wanted}"]
    findings = [
        f"{field} is {clients[0].get(field)!r}"
        for field, value in NO_FLOW.items()
        if clients[0].get(field) is not value
    ]
    if clients[0].get("secret") != secret:
        findings.append(f"secret is not the credential of {wanted}")
    accounts = [u for u in realm["users"] if u.get("serviceAccountClientId") == wanted]
    if len(accounts) != 1:
        return [*findings, f"{len(accounts)} service accounts"]
    held = accounts[0].get("clientRoles", {})
    if set(held) != {REALM_MANAGEMENT} or set(held[REALM_MANAGEMENT]) != roles:
        findings.append(f"client roles are {held}")
    if accounts[0]["username"] != f"service-account-{wanted}":
        findings.append(f"service account is {accounts[0]['username']}")
    return findings


def members_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps ``workspace-members`` from no flow and exactly its two roles.
    """
    return service_account_findings(
        realm, MEMBERS_CLIENT, MEMBERS_ROLES, MEMBERS_CLIENT_SECRET
    )


def export_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps ``export`` from no flow and exactly its three read roles.
    """
    return service_account_findings(
        realm, EXPORT_CLIENT, EXPORT_ROLES, EXPORT_CLIENT_SECRET
    )


class TestConsumerClients(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm()

    def test_each_consumer_has_a_confidential_client(self) -> None:
        for application_id in CONSUMERS:
            with self.subTest(consumer=application_id):
                self.assertEqual(login_findings(self.realm, application_id), [])

    def test_the_login_check_catches_a_public_or_foreign_client(self) -> None:
        for field, value in (
            ("publicClient", True),
            ("directAccessGrantsEnabled", True),
            ("redirectUris", [origin("web-app-gitea") + "/*"]),
        ):
            with self.subTest(field=field):
                planted = copy.deepcopy(self.realm)
                clients_of(planted, client_id(STORE))[0][field] = value
                self.assertTrue(login_findings(planted, STORE))

    def test_the_store_client_has_a_base_url(self) -> None:
        client = clients_of(self.realm, client_id(STORE))[0]
        self.assertEqual(client["rootUrl"], origin(STORE))
        self.assertEqual(client["baseUrl"], origin(STORE))

    def test_only_the_store_client_carries_the_workspace_roles_scope(self) -> None:
        holders = [
            c["clientId"]
            for c in self.realm["clients"]
            if SCOPE in c.get("defaultClientScopes", [])
            or SCOPE in c.get("optionalClientScopes", [])
        ]
        self.assertEqual(holders, [client_id(STORE)])


class TestStoreClientIsALoginClientOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm()

    def test_the_store_client_is_a_login_client_only(self) -> None:
        self.assertEqual(admin_findings(self.realm, client_id(STORE)), [])

    def test_the_admin_check_catches_a_planted_service_account(self) -> None:
        planted = copy.deepcopy(self.realm)
        clients_of(planted, client_id(STORE))[0]["serviceAccountsEnabled"] = True
        planted["users"].append(
            {
                "username": f"service-account-{client_id(STORE)}",
                "serviceAccountClientId": client_id(STORE),
            }
        )
        self.assertEqual(len(admin_findings(planted, client_id(STORE))), 2)

    def test_the_admin_check_catches_a_planted_manage_organizations(self) -> None:
        planted = copy.deepcopy(self.realm)
        planted["users"].append(
            {
                "username": f"service-account-{client_id(STORE)}",
                "serviceAccountClientId": client_id(STORE),
                "clientRoles": {REALM_MANAGEMENT: ["manage-organizations"]},
            }
        )
        self.assertTrue(admin_findings(planted, client_id(STORE)))

    def test_the_store_client_names_itself_as_audience(self) -> None:
        self.assertEqual(audience_findings(self.realm, client_id(STORE)), [])

    def test_the_audience_check_catches_a_dropped_mapper(self) -> None:
        planted = copy.deepcopy(self.realm)
        clients_of(planted, client_id(STORE))[0]["protocolMappers"] = []
        self.assertTrue(audience_findings(planted, client_id(STORE)))


def fixture_findings(realm: dict) -> list[str]:
    """
    Args:
        realm: the parsed realm import.

    Returns:
        What keeps the store fixture from the shape of the store's client.
    """
    clients = clients_of(realm, STORE_FIXTURE)
    if len(clients) != 1:
        return [f"{len(clients)} clients {STORE_FIXTURE}"]
    client = clients[0]
    own = origin("web-app-semaphore")
    findings = [
        f"{field} is {client.get(field)!r}"
        for field, value in LOGIN_CLIENT.items()
        if client.get(field) is not value
    ]
    findings.extend(
        f"{field} is {client.get(field)!r}"
        for field in ("rootUrl", "baseUrl")
        if client.get(field) != own
    )
    if client.get("secret") != STORE_FIXTURE_CLIENT_SECRET:
        findings.append("secret is not the fixture credential")
    if SCOPE not in client["defaultClientScopes"]:
        findings.append(f"{SCOPE} is no default scope")
    findings.extend(audience_findings(realm, STORE_FIXTURE))
    findings.extend(admin_findings(realm, STORE_FIXTURE))
    return findings


def semaphore_invite_client_ids() -> list[object]:
    """
    Returns:
        ``services.semaphore.workspaces.invite_client_id`` of ``web-app-semaphore``,
        first from ``meta/services.yml``, then as each variant sets it.
    """
    base = load_yaml_any(str(SEMAPHORE_DIR / ROLE_FILE_META_SERVICES))
    variants = load_yaml_any(str(SEMAPHORE_DIR / ROLE_FILE_META_VARIANTS))
    return [base["semaphore"]["workspaces"]["invite_client_id"]] + [
        (
            ((variant.get("services") or {}).get("semaphore") or {}).get("workspaces")
            or {}
        ).get("invite_client_id")
        for variant in variants
    ]


class TestStoreFixture(unittest.TestCase):
    def test_only_semaphore_variant_0_names_the_fixture(self) -> None:
        named = [
            position
            for position, value in enumerate(semaphore_invite_client_ids())
            if value == STORE_FIXTURE
        ]
        self.assertEqual(named, [1])

    def test_the_fixture_is_shaped_like_the_store_client(self) -> None:
        self.assertEqual(fixture_findings(realm(invite_client_id=STORE_FIXTURE)), [])

    def test_negative_control_no_fixture_unless_its_id_is_the_invite_client(
        self,
    ) -> None:
        for enabled, invite in (
            (True, None),
            (True, client_id(STORE)),
            (False, STORE_FIXTURE),
        ):
            with self.subTest(organizations=enabled, invite=invite):
                self.assertEqual(clients_of(realm(enabled, invite), STORE_FIXTURE), [])

    def test_negative_control_the_fixture_check_catches_a_service_account(
        self,
    ) -> None:
        planted = realm(invite_client_id=STORE_FIXTURE)
        clients_of(planted, STORE_FIXTURE)[0]["serviceAccountsEnabled"] = True
        self.assertTrue(fixture_findings(planted))


class TestMembersClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm()

    def test_secrets_declare_a_sha256_credential(self) -> None:
        secrets = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SECRETS))
        credential = secrets["credentials"]["workspace_members_client_secret"]
        self.assertEqual(credential["algorithm"], "sha256")
        self.assertEqual(credential["validation"], "^[a-f0-9]{64}$")

    def test_the_members_client_holds_exactly_two_roles(self) -> None:
        self.assertEqual(members_findings(self.realm), [])

    def test_the_members_check_catches_manage_realm(self) -> None:
        planted = copy.deepcopy(self.realm)
        account = next(
            u
            for u in planted["users"]
            if u.get("serviceAccountClientId") == MEMBERS_CLIENT
        )
        account["clientRoles"][REALM_MANAGEMENT].append("manage-realm")
        self.assertTrue(members_findings(planted))

    def test_the_members_check_catches_an_enabled_flow(self) -> None:
        planted = copy.deepcopy(self.realm)
        clients_of(planted, MEMBERS_CLIENT)[0]["standardFlowEnabled"] = True
        self.assertTrue(members_findings(planted))

    def test_without_organizations_no_members_client_exists(self) -> None:
        off = realm(False)
        self.assertEqual(clients_of(off, MEMBERS_CLIENT), [])
        self.assertFalse(
            [
                u
                for u in off["users"]
                if u.get("serviceAccountClientId") == MEMBERS_CLIENT
            ]
        )


class TestExportClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.realm = realm()

    def test_the_client_id_is_export_and_unique(self) -> None:
        self.assertEqual(ROLE_VARS["KEYCLOAK_EXPORT_CLIENT_ID"], EXPORT_CLIENT)
        self.assertEqual(len(clients_of(self.realm, EXPORT_CLIENT)), 1)
        ids = [c["clientId"] for c in self.realm["clients"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_secrets_declare_a_sha256_credential(self) -> None:
        secrets = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SECRETS))
        credential = secrets["credentials"]["export_client_secret"]
        self.assertEqual(credential["algorithm"], "sha256")
        self.assertEqual(credential["validation"], "^[a-f0-9]{64}$")
        self.assertEqual(
            ROLE_VARS["KEYCLOAK_EXPORT_CLIENT_SECRET"],
            "{{ lookup('config', application_id, 'secrets.credentials.export_client_secret') }}",
        )

    def test_the_export_client_holds_exactly_three_read_roles(self) -> None:
        self.assertEqual(export_findings(self.realm), [])

    def test_the_export_check_catches_a_fourth_role(self) -> None:
        for role in ("manage-users", "manage-events", "view-realm"):
            with self.subTest(role=role):
                planted = copy.deepcopy(self.realm)
                account = next(
                    u
                    for u in planted["users"]
                    if u.get("serviceAccountClientId") == EXPORT_CLIENT
                )
                account["clientRoles"][REALM_MANAGEMENT].append(role)
                self.assertTrue(export_findings(planted))

    def test_the_export_check_catches_an_enabled_flow_or_a_shared_secret(
        self,
    ) -> None:
        for field, value in (
            ("standardFlowEnabled", True),
            ("directAccessGrantsEnabled", True),
            ("secret", MEMBERS_CLIENT_SECRET),
        ):
            with self.subTest(field=field):
                planted = copy.deepcopy(self.realm)
                clients_of(planted, EXPORT_CLIENT)[0][field] = value
                self.assertTrue(export_findings(planted))

    def test_the_converge_holds_the_same_roles_as_the_import(self) -> None:
        expression = ROLE_VARS["KEYCLOAK_SERVICE_ACCOUNT_ROLES"].strip()
        converged = Environment(
            undefined=StrictUndefined, autoescape=select_autoescape()
        ).compile_expression(expression.removeprefix("{{").removesuffix("}}"))(
            **organizations_context(True)
        )
        self.assertEqual(
            {client: set(roles) for client, roles in converged.items()},
            {MEMBERS_CLIENT: MEMBERS_ROLES, EXPORT_CLIENT: EXPORT_ROLES},
        )
        self.assertIn(
            "KEYCLOAK_EXPORT_CLIENT_ID", ROLE_VARS["KEYCLOAK_WORKSPACE_CLIENT_IDS"]
        )

    def test_without_organizations_no_export_client_exists(self) -> None:
        off = realm(False)
        self.assertEqual(clients_of(off, EXPORT_CLIENT), [])
        self.assertFalse(
            [
                u
                for u in off["users"]
                if u.get("serviceAccountClientId") == EXPORT_CLIENT
            ]
        )


if __name__ == "__main__":
    unittest.main()
