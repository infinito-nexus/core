from __future__ import annotations

import importlib.util
import json
import re
import unittest
from unittest import mock

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
IMPORT_DIR = ROLE_DIR / "templates/import"
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
LDAP_VARS = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))
LDAP_USER_ATTRIBUTES = {
    **LDAP_VARS["LDAP"]["USER"]["ATTRIBUTES"],
    "ID": "uid",
}


def profile_attributes() -> list[dict]:
    """Render the role's profile registry against the directory attribute names."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    ldap = {"USER": {"ATTRIBUTES": LDAP_USER_ATTRIBUTES}}
    return [
        {**entry, "ldap": env.from_string(entry["ldap"]).render(LDAP=ldap)}
        for entry in ROLE_VARS["KEYCLOAK_PROFILE_ATTRIBUTES"]
    ]


def role_filters() -> dict:
    """Load the role's own Jinja filters the realm import relies on."""
    spec = importlib.util.spec_from_file_location(
        "keycloak_ldap_filters", ROLE_DIR / "filter_plugins/ldap_filters.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def secondary_pattern(domain: str) -> str:
    """Render the role's secondary address pattern for a mailbox domain."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["regex_escape"] = re.escape
    return env.from_string(ROLE_VARS["KEYCLOAK_EMAIL_SECONDARY_PATTERN"]).render(
        KEYCLOAK_EMAIL_DOMAIN=domain
    )


APP_URL = "https://suite.crm.example.com"
ONION_URL = "http://suite.crm." + "a" * 56 + ".onion"

CONTEXT = {
    "KEYCLOAK_REALM": "example.com",
    "KEYCLOAK_REALM_URL": "https://auth.example.com/realms/example.com",
    "KEYCLOAK_CLIENT_ID": "example.com",
    "KEYCLOAK_REDIRECT_URIS": ["https://suite.crm.example.com/*"],
    "KEYCLOAK_WEB_ORIGINS": ["https://suite.crm.example.com"],
    "KEYCLOAK_POST_LOGOUT_URIS": "+",
    "KEYCLOAK_FRONTCHANNEL_LOGOUT_URL": "https://logout.example.com",
    "KEYCLOAK_RBAC_GROUP_CLAIM": "groups",
    "KEYCLOAK_RECAPTCHA_KEY": "",
    "KEYCLOAK_RECAPTCHA_SECRET": "",
    "KEYCLOAK_RECAPTCHA_ENABLED": False,
    "KEYCLOAK_REALM_TOTP_ENABLED": False,
    "KEYCLOAK_LDAP_ENABLED": True,
    "KEYCLOAK_MOODLE_ENABLED": True,
    "KEYCLOAK_RESERVED_USERNAMES_REGEX": "^(root|admin)$",
    "IAM_USERNAME_MAX_LENGTH": 15,
    "IAM_ACCOUNT_MAX_LENGTH": 20,
    "IAM_USERNAME_PATTERNS": ["[a-z0-9_]+", "[a-y0-9]+"],
    "KEYCLOAK_LDAP_USER_OBJECT_CLASSES": "inetOrgPerson, organizationalPerson",
    "KEYCLOAK_LDAP_CMP_NAME": "ldap",
    "KEYCLOAK_LDAP_URL": "ldap://openldap:389",
    "KEYCLOAK_LDAP_BIND_DN": "cn=admin,dc=example,dc=com",
    "KEYCLOAK_LDAP_BIND_PW": "secret",
    "KEYCLOAK_LDAP_CONNECTION_POOLING": "true",
    "KEYCLOAK_LDAP_SYNC_CHANGES_PERIOD": "86400",
    "KEYCLOAK_LDAP_SYNC_FULL_PERIOD": "604800",
    "KEYCLOAK_RBAC_GROUP_NAME": "groups",
    "KEYCLOAK_PROFILE_ATTRIBUTES": profile_attributes(),
    "KEYCLOAK_PROFILE_GROUPS": ROLE_VARS["KEYCLOAK_PROFILE_GROUPS"],
    "KEYCLOAK_PROFILE_MAPPER_PREFIX": ROLE_VARS["KEYCLOAK_PROFILE_MAPPER_PREFIX"],
    "KEYCLOAK_EMAIL_POLICY": "external",
    "KEYCLOAK_EMAIL_MAILBOX": False,
    "KEYCLOAK_EMAIL_SMTP": False,
    "KEYCLOAK_EMAIL_VERIFY": False,
    "KEYCLOAK_EMAIL_SECONDARY_REQUIRED": True,
    "KEYCLOAK_EMAIL_DOMAIN": "example.com",
    "KEYCLOAK_EMAIL_SECONDARY_PATTERN": secondary_pattern("example.com"),
    "KEYCLOAK_EMAIL_POLICY_ATTRIBUTE": ROLE_VARS["KEYCLOAK_EMAIL_POLICY_ATTRIBUTE"],
    "KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE": ROLE_VARS["KEYCLOAK_EMAIL_MAILBOX_ATTRIBUTE"],
    "KEYCLOAK_REGISTRATION_ALLOWED": ROLE_VARS["KEYCLOAK_REGISTRATION_ALLOWED"],
    "LDAP_ONLY": False,
    "OIDC": {
        "CLIENT": {"SECRET": "s3cret", "ID": "example.com"},
        "ATTRIBUTES": {"USERNAME": "preferred_username"},
    },
    "LDAP": {
        "DN": {
            "OU": {
                "USERS": "ou=users,dc=example,dc=com",
                "ROLES": "ou=roles,dc=example,dc=com",
            }
        },
        "RBAC": {
            "FLAVORS": ["groupOfNames"],
            "MEMBER_ATTRIBUTE": LDAP_VARS["LDAP"]["RBAC"]["MEMBER_ATTRIBUTE"],
        },
        "USER": {"ATTRIBUTES": LDAP_USER_ATTRIBUTES},
    },
}


def path_join(parts):
    head, *tail = list(parts)
    return "/".join([head.rstrip("/"), *[p.strip("/") for p in tail]])


def fake_lookup(name, *_args, **_kwargs):
    """Stub the lookups the realm import performs.

    Args:
        name: the lookup plugin the template asked for.
    """
    if name == "email":
        return {"enabled": False}
    if name == "config":
        return str(_args[-1]).rsplit(".", 1)[-1]
    if name == "network_urls":
        return [_args[0]]
    return APP_URL


def onion_sibling(url: str) -> list[str]:
    """
    Args:
        url: the URL lookup('network_urls') is asked for.

    Returns:
        The URL on clearnet and on the onion sibling of the SAML app's host.
    """
    if not url.startswith(APP_URL):
        return [url]
    return [url, ONION_URL + url.removeprefix(APP_URL)]


def render(
    saml_apps: list[str],
    client_apps: list[str] | None = None,
    network_urls=None,
    overrides: dict | None = None,
) -> str:
    """
    Args:
        saml_apps: KEYCLOAK_SAML_APPS.
        client_apps: KEYCLOAK_DECLARED_CLIENT_APPS.
        network_urls: answer of lookup('network_urls', url); None serves one network.
        overrides: context values replacing those of CONTEXT.
    """

    def lookup(name, *args, **kwargs):
        if name == "network_urls" and network_urls is not None:
            return network_urls(*args)
        return fake_lookup(name, *args, **kwargs)

    env = Environment(
        loader=FileSystemLoader([str(IMPORT_DIR), str(PROJECT_ROOT)]),
        trim_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["path_join"] = path_join
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    env.filters.update(role_filters())
    return env.get_template("realm.json.j2").render(
        KEYCLOAK_SAML_APPS=saml_apps,
        KEYCLOAK_DECLARED_CLIENT_APPS=client_apps or [],
        lookup=lookup,
        application_id="web-app-keycloak",
        DOMAIN_PRIMARY="example.com",
        **{**CONTEXT, **(overrides or {})},
    )


def username_pattern() -> re.Pattern[str]:
    realm = json.loads(render([]))
    provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
    username = next(
        attribute
        for attribute in profile["attributes"]
        if attribute["name"] == "username"
    )
    return re.compile(username["validations"]["pattern"]["pattern"])


class TestRealmImportJson(unittest.TestCase):
    def test_app_declared_clients_join_the_realm(self) -> None:
        """An app in KEYCLOAK_DECLARED_CLIENT_APPS ships its own client fragment."""
        realm = json.loads(render([], client_apps=["web-app-stalwart"]))
        client_ids = [c["clientId"] for c in realm["clients"]]
        self.assertIn("webui", client_ids)
        self.assertIn("webmail", client_ids)

    def test_no_declaring_apps_means_no_extra_clients(self) -> None:
        with_apps = json.loads(render([], client_apps=["web-app-stalwart"]))
        without = json.loads(render([]))
        self.assertEqual(len(with_apps["clients"]) - len(without["clients"]), 2)

    def test_realm_is_valid_json_without_saml_apps(self) -> None:
        realm = json.loads(render([]))
        client_ids = [c["clientId"] for c in realm["clients"]]
        self.assertNotIn(path_join([APP_URL, "saml/metadata"]), client_ids)

    def test_the_declarative_profile_declares_uidnumber(self) -> None:
        """Keycloak drops writes to an attribute the profile does not declare, and
        the unmanaged-attribute policy is DISABLED by default, so an undeclared
        uidNumber leaves the mattermost-id mapper with nothing to emit and the
        OIDC callback fails on a user id of 0."""
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        declared = {attribute["name"] for attribute in profile["attributes"]}
        self.assertIn("uidNumber", declared)

    def test_every_profile_attribute_has_an_ldap_mapper(self) -> None:
        realm = json.loads(render([]))
        ldap = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
        mappers = {
            m["name"]: m["config"]
            for m in ldap["subComponents"][
                "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
            ]
        }
        prefix = CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"]
        for attribute in CONTEXT["KEYCLOAK_PROFILE_ATTRIBUTES"]:
            config = mappers[prefix + attribute["name"]]
            self.assertEqual(config["ldap.attribute"], [attribute["ldap"]])
            self.assertEqual(config["user.model.attribute"], [attribute["name"]])

    def test_profile_mappers_do_not_depend_on_moodle(self) -> None:
        context = {**CONTEXT, "KEYCLOAK_MOODLE_ENABLED": False}
        with mock.patch.dict(CONTEXT, context):
            realm = json.loads(render([]))
        ldap = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
        names = {
            m["name"]
            for m in ldap["subComponents"][
                "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
            ]
        }
        self.assertIn(CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"] + "country", names)
        self.assertNotIn("moodle:country", names)

    def test_contact_fields_are_user_editable_and_organization_fields_are_not(
        self,
    ) -> None:
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        attributes = {a["name"]: a for a in profile["attributes"]}
        self.assertEqual(
            attributes["phoneNumber"]["permissions"]["edit"], ["admin", "user"]
        )
        self.assertEqual(attributes["department"]["permissions"]["edit"], ["admin"])
        self.assertEqual(attributes["nextcloudQuota"]["permissions"]["edit"], ["admin"])
        self.assertEqual(
            {g["name"] for g in profile["groups"]},
            {"user-metadata", *CONTEXT["KEYCLOAK_PROFILE_GROUPS"]},
        )

    def test_the_username_length_follows_the_platform_limit(self) -> None:
        """Registration must admit the longest account name, so the profile
        carries IAM_ACCOUNT_MAX_LENGTH rather than Keycloak's own 255. Agent
        names reach that ceiling; humans stay under IAM_USERNAME_MAX_LENGTH by
        the users lint."""
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        username = next(
            attribute
            for attribute in profile["attributes"]
            if attribute["name"] == "username"
        )
        self.assertEqual(
            username["validations"]["length"]["max"],
            CONTEXT["IAM_ACCOUNT_MAX_LENGTH"],
        )

    def test_the_username_pattern_admits_only_what_every_app_accepts(self) -> None:
        pattern = username_pattern()
        self.assertTrue(pattern.match("alice19"))
        for refused in ("root", "al0ce", "alice_x", "zoe", "Alice"):
            with self.subTest(username=refused):
                self.assertIsNone(pattern.match(refused))

    def test_the_username_pattern_admits_the_agent_form(self) -> None:
        pattern = username_pattern()
        for agent in ("mant0alice", "cnsl0a1b2c3"):
            with self.subTest(username=agent):
                self.assertTrue(pattern.match(agent))
        for refused in (
            "mant0al0ce",
            "mant00alice",
            "man0alice",
            "0mantalice",
            "mant0",
            "mant0Alice",
            "mant0al_ce",
        ):
            with self.subTest(username=refused):
                self.assertIsNone(pattern.match(refused))

    def test_only_an_admin_may_change_an_email_address(self) -> None:
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        email = next(
            attribute
            for attribute in profile["attributes"]
            if attribute["name"] == "email"
        )
        self.assertEqual(
            email["permissions"]["edit"],
            ["admin"],
            "applications resolve their account by this address and the realm does "
            "not verify a change, so a self-service edit takes over whichever account "
            "the typed address names",
        )
        self.assertEqual(email["permissions"]["view"], ["admin", "user"])

    def test_realm_is_valid_json_with_one_saml_app(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        clients = {c["clientId"]: c for c in realm["clients"]}
        client = clients[path_join([APP_URL, "saml/metadata"])]
        self.assertEqual(client["protocol"], "saml")
        self.assertEqual(client["redirectUris"], [path_join([APP_URL, "saml/acs"])])

    def test_saml_client_accepts_the_assertion_consumer_of_every_network_sibling(
        self,
    ) -> None:
        realm = json.loads(render(["web-app-suitecrm"], network_urls=onion_sibling))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        self.assertEqual(
            client["redirectUris"],
            [path_join([APP_URL, "saml/acs"]), path_join([ONION_URL, "saml/acs"])],
            "Keycloak checks the AssertionConsumerServiceURL of the request against "
            "redirectUris, so an onion login names an ACS it must list",
        )
        self.assertEqual(
            client["attributes"]["saml_assertion_consumer_url_post"],
            path_join([APP_URL, "saml/acs"]),
        )

    def test_realm_is_valid_json_with_several_saml_apps(self) -> None:
        realm = json.loads(render(["web-app-suitecrm", "web-app-other"]))
        saml = [c for c in realm["clients"] if c.get("protocol") == "saml"]
        self.assertEqual(len(saml), 2)

    def test_saml_client_asserts_groups_and_every_profile_attribute(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        mappers = {m["name"]: m for m in client["protocolMappers"]}
        groups = mappers[CONTEXT["KEYCLOAK_RBAC_GROUP_CLAIM"]]
        self.assertEqual(groups["protocolMapper"], "saml-group-membership-mapper")
        self.assertEqual(groups["config"]["full.path"], "true")
        prefix = CONTEXT["KEYCLOAK_PROFILE_MAPPER_PREFIX"]
        for attribute in CONTEXT["KEYCLOAK_PROFILE_ATTRIBUTES"]:
            mapper = mappers[f"{prefix}{attribute['name']}"]
            self.assertEqual(mapper["protocolMapper"], "saml-user-attribute-mapper")
            self.assertEqual(mapper["config"]["user.attribute"], attribute["name"])
            self.assertEqual(mapper["config"]["attribute.name"], attribute["ldap"])

    def test_saml_client_omits_the_role_list_scope(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        self.assertEqual(client["defaultClientScopes"], [])

    def test_the_allowed_origins_mapper_stays_out_of_the_access_token(self) -> None:
        """The claim grows with every registered origin and rides along in
        X-Forwarded-Access-Token, where an app server's header limit ends the
        request; Keycloak's own CORS reads client.webOrigins, not the claim."""
        realm = json.loads(render([]))
        scope = next(s for s in realm["clientScopes"] if s["name"] == "web-origins")
        mapper = next(
            m
            for m in scope["protocolMappers"]
            if m["protocolMapper"] == "oidc-allowed-origins-mapper"
        )
        self.assertEqual(mapper["config"]["access.token.claim"], "false")
        self.assertEqual(mapper["config"]["introspection.token.claim"], "true")

    def test_saml_client_maps_the_username_attribute_the_app_reads(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        names = {
            m["config"]["attribute.name"]
            for m in client["protocolMappers"]
            if m["name"] == "username"
        }
        self.assertEqual(names, {CONTEXT["OIDC"]["ATTRIBUTES"]["USERNAME"]})


CLIENT_APPS = sorted(
    path.parts[-4]
    for path in PROJECT_ROOT.glob("roles/*/templates/keycloak/clients.json.j2")
)
REALM_MANAGEMENT = "realm-management"
EVENT_SETTINGS = {
    "eventsEnabled": False,
    "eventsListeners": ["jboss-logging"],
    "enabledEventTypes": [],
    "adminEventsEnabled": True,
    "adminEventsDetailsEnabled": False,
}


ALLOWED_ORIGINS_MAPPER = "oidc-allowed-origins-mapper"


def puts_allowed_origins_into_access_tokens(entity: dict) -> bool:
    """Whether a client or client scope writes allowed-origins into the access token.

    Args:
        entity: a client or client scope representation.
    """
    return any(
        mapper["protocolMapper"] == ALLOWED_ORIGINS_MAPPER
        and mapper["config"].get("access.token.claim") == "true"
        for mapper in entity.get("protocolMappers", [])
    )


def realm_managing_service_accounts(realm: dict) -> list[str]:
    """Return the service-account users of ``realm`` that hold a realm-management role.

    Args:
        realm: the parsed realm render.
    """
    return [
        user["username"]
        for user in realm["users"]
        if "serviceAccountClientId" in user
        and user.get("clientRoles", {}).get(REALM_MANAGEMENT)
    ]


class TestLogoutTrustBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.realm = json.loads(render([], client_apps=CLIENT_APPS))

    def test_the_realm_renders_on_the_credentials_it_already_had(self) -> None:
        secrets = {
            client["secret"]
            for client in self.realm["clients"]
            if client.get("protocol") == "openid-connect" and "secret" in client
        }
        self.assertEqual(secrets, {CONTEXT["OIDC"]["CLIENT"]["SECRET"]})

    def test_no_service_account_user_holds_a_realm_management_role(self) -> None:
        self.assertTrue(
            [u for u in self.realm["users"] if "serviceAccountClientId" in u],
            "the shared client's service account is part of the render",
        )
        self.assertEqual(realm_managing_service_accounts(self.realm), [])

    def test_a_realm_management_grant_to_a_service_account_is_caught(self) -> None:
        user = next(u for u in self.realm["users"] if "serviceAccountClientId" in u)
        user["clientRoles"] = {REALM_MANAGEMENT: ["manage-users"]}
        self.assertEqual(
            realm_managing_service_accounts(self.realm), [user["username"]]
        )

    def _shared_client(self) -> dict:
        return next(
            c
            for c in self.realm["clients"]
            if c["clientId"] == CONTEXT["KEYCLOAK_CLIENT_ID"]
        )

    def _web_origins_scope(self) -> dict:
        return next(s for s in self.realm["clientScopes"] if s["name"] == "web-origins")

    def test_the_shared_client_carries_no_mapper_of_its_own(self) -> None:
        self.assertNotIn("protocolMappers", self._shared_client())

    def test_the_shared_client_keeps_allowed_origins_out_of_its_tokens(self) -> None:
        self.assertFalse(puts_allowed_origins_into_access_tokens(self._shared_client()))

    def test_an_allowed_origins_mapper_on_the_shared_client_is_caught(self) -> None:
        client = self._shared_client()
        client["protocolMappers"] = [
            {
                "protocolMapper": ALLOWED_ORIGINS_MAPPER,
                "config": {"access.token.claim": "true"},
            }
        ]
        self.assertTrue(puts_allowed_origins_into_access_tokens(client))

    def test_the_web_origins_scope_keeps_allowed_origins_out_of_access_tokens(
        self,
    ) -> None:
        self.assertFalse(
            puts_allowed_origins_into_access_tokens(self._web_origins_scope())
        )

    def test_allowed_origins_in_the_web_origins_scope_is_caught(self) -> None:
        scope = self._web_origins_scope()
        for mapper in scope["protocolMappers"]:
            mapper["config"]["access.token.claim"] = "true"
        self.assertTrue(puts_allowed_origins_into_access_tokens(scope))

    def test_only_the_dashboard_client_puts_allowed_origins_into_access_tokens(
        self,
    ) -> None:
        self.assertEqual(
            [
                c["clientId"]
                for c in self.realm["clients"]
                if puts_allowed_origins_into_access_tokens(c)
            ],
            ["dashboard"],
            "the fake config lookup answers the last segment of the client path",
        )

    def test_no_logout_client_joins_the_realm(self) -> None:
        self.assertNotIn("web-svc-logout", CLIENT_APPS)
        client_ids = {client["clientId"] for client in self.realm["clients"]}
        self.assertFalse({cid for cid in client_ids if "logout" in cid})

    def test_the_realm_keeps_its_event_settings(self) -> None:
        self.assertEqual(
            {key: self.realm[key] for key in EVENT_SETTINGS}, EVENT_SETTINGS
        )
        self.assertNotIn("eventsExpiration", self.realm)

    def test_the_realm_enables_fine_grained_admin_permissions(self) -> None:
        self.assertIs(self.realm["adminPermissionsEnabled"], True)

    def test_the_account_api_stays_open_to_the_users_own_token(self) -> None:
        default_roles = next(
            role
            for role in self.realm["roles"]["realm"]
            if role["name"] == f"default-roles-{CONTEXT['KEYCLOAK_REALM']}"
        )
        self.assertIn(
            "manage-account", default_roles["composites"]["client"]["account"]
        )
        self.assertIn(
            "account", {client["clientId"] for client in self.realm["clients"]}
        )


MAILBOX = {"KEYCLOAK_EMAIL_POLICY": "mailbox", "KEYCLOAK_EMAIL_MAILBOX": True}
SMTP = {"KEYCLOAK_EMAIL_SMTP": True}


def email_verify(context: dict) -> bool:
    """Render the role's KEYCLOAK_EMAIL_VERIFY expression for a context."""
    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = bool
    rendered = env.from_string(ROLE_VARS["KEYCLOAK_EMAIL_VERIFY"]).render(**context)
    return rendered == "True"


def realm_for(overrides: dict, saml_apps: list[str] | None = None) -> dict:
    context = {**CONTEXT, **overrides}
    return json.loads(
        render(
            saml_apps or [],
            overrides={**overrides, "KEYCLOAK_EMAIL_VERIFY": email_verify(context)},
        )
    )


def profile_of(realm: dict) -> dict:
    provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
    profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
    return {attribute["name"]: attribute for attribute in profile["attributes"]}


def ldap_mappers_of(realm: dict) -> dict:
    provider = realm["components"]["org.keycloak.storage.UserStorageProvider"][0]
    return {
        mapper["name"]: mapper
        for mapper in provider["subComponents"][
            "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
        ]
    }


def email_scope_mappers_of(realm: dict) -> dict:
    scope = next(s for s in realm["clientScopes"] if s["name"] == "email")
    return {mapper["name"]: mapper for mapper in scope["protocolMappers"]}


def update_email_of(realm: dict) -> dict:
    return next(a for a in realm["requiredActions"] if a["alias"] == "UPDATE_EMAIL")


class TestEmailPolicy(unittest.TestCase):
    def test_an_external_realm_with_smtp_lets_the_user_change_the_primary_by_link(
        self,
    ) -> None:
        realm = realm_for(SMTP)
        email = profile_of(realm)["email"]
        self.assertEqual(email["permissions"]["edit"], ["admin", "user"])
        self.assertEqual(email["required"], {"roles": ["user"]})
        self.assertTrue(realm["verifyEmail"])
        self.assertTrue(update_email_of(realm)["enabled"])
        self.assertEqual(update_email_of(realm)["config"], {"verifyEmail": "true"})
        self.assertEqual(
            ldap_mappers_of(realm)["email"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["MAIL"]],
        )
        self.assertNotIn("mailbox", ldap_mappers_of(realm))
        self.assertNotIn("mailbox", profile_of(realm))
        self.assertEqual(
            email_scope_mappers_of(realm)["email"]["config"]["user.attribute"], "email"
        )
        self.assertEqual(realm["attributes"]["infinitoEmailPolicy"], "external")

    def test_an_external_realm_without_smtp_leaves_the_address_to_admins(
        self,
    ) -> None:
        realm = realm_for({})
        self.assertEqual(profile_of(realm)["email"]["permissions"]["edit"], ["admin"])
        self.assertFalse(realm["verifyEmail"])
        self.assertFalse(update_email_of(realm)["enabled"])

    def test_a_mailbox_realm_keeps_the_primary_out_of_the_users_reach(self) -> None:
        realm = realm_for({**MAILBOX, **SMTP})
        profile = profile_of(realm)
        self.assertEqual(profile["mailbox"]["permissions"]["edit"], ["admin"])
        self.assertEqual(profile["mailbox"]["permissions"]["view"], ["admin", "user"])
        self.assertEqual(profile["email"]["permissions"]["edit"], ["admin", "user"])
        self.assertFalse(realm["verifyEmail"])
        self.assertTrue(update_email_of(realm)["enabled"])
        self.assertEqual(update_email_of(realm)["config"], {"verifyEmail": "true"})
        mappers = ldap_mappers_of(realm)
        self.assertEqual(
            mappers["mailbox"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["MAIL"]],
        )
        self.assertEqual(mappers["mailbox"]["config"]["read.only"], ["true"])
        self.assertEqual(
            mappers["mailbox"]["config"]["always.read.value.from.ldap"], ["true"]
        )
        self.assertEqual(
            mappers["email"]["config"]["ldap.attribute"],
            [LDAP_USER_ATTRIBUTES["SECONDARY_MAIL"]],
        )
        self.assertEqual(realm["attributes"]["infinitoEmailPolicy"], "mailbox")

    def test_a_mailbox_realm_hands_apps_the_mailbox_as_verified_email(self) -> None:
        realm = realm_for({**MAILBOX, **SMTP}, saml_apps=["web-app-suitecrm"])
        scope = email_scope_mappers_of(realm)
        self.assertEqual(scope["email"]["config"]["user.attribute"], "mailbox")
        self.assertEqual(
            scope["email verified"]["protocolMapper"], "oidc-hardcoded-claim-mapper"
        )
        self.assertEqual(scope["email verified"]["config"]["claim.value"], "true")
        saml = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        saml_email = next(m for m in saml["protocolMappers"] if m["name"] == "email")
        self.assertEqual(saml_email["protocolMapper"], "saml-user-attribute-mapper")
        self.assertEqual(saml_email["config"]["user.attribute"], "mailbox")

    def test_a_secondary_address_in_the_mailbox_domain_is_refused(self) -> None:
        email = profile_of(realm_for({**MAILBOX, **SMTP}))["email"]
        pattern = re.compile(email["validations"]["pattern"]["pattern"])
        self.assertIsNone(pattern.match("biber@example.com"))
        self.assertIsNone(pattern.match("Biber@EXAMPLE.COM"))
        self.assertIsNotNone(pattern.match("biber@example.org"))
        self.assertIsNotNone(pattern.match("biber@sub.example.com.evil"))

    def test_the_secondary_address_is_required_only_once_registration_is_open(
        self,
    ) -> None:
        closed = profile_of(realm_for({**MAILBOX, **SMTP}))["email"]
        self.assertNotIn("required", closed)
        opened = profile_of(
            realm_for({**MAILBOX, **SMTP, "KEYCLOAK_REGISTRATION_ALLOWED": True})
        )["email"]
        self.assertEqual(opened["required"], {"roles": ["user"]})
        switched_off = profile_of(
            realm_for(
                {
                    **MAILBOX,
                    **SMTP,
                    "KEYCLOAK_REGISTRATION_ALLOWED": True,
                    "KEYCLOAK_EMAIL_SECONDARY_REQUIRED": False,
                }
            )
        )["email"]
        self.assertNotIn("required", switched_off)

    def test_no_policy_allows_duplicate_emails(self) -> None:
        for overrides in ({}, SMTP, {**MAILBOX, **SMTP}):
            with self.subTest(overrides=overrides):
                self.assertFalse(realm_for(overrides)["duplicateEmailsAllowed"])


if __name__ == "__main__":
    unittest.main()
