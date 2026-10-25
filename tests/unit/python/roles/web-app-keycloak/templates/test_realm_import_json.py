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


APP_URL = "https://suite.crm.example.com"

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
    "IAM_USERNAME_PATTERNS": ["[a-z0-9_]+", "[a-y1-9]+"],
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
    return APP_URL


def render(saml_apps: list[str], client_apps: list[str] | None = None) -> str:
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
        lookup=fake_lookup,
        application_id="web-app-keycloak",
        DOMAIN_PRIMARY="example.com",
        **CONTEXT,
    )


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
        realm = json.loads(render([]))
        provider = realm["components"]["org.keycloak.userprofile.UserProfileProvider"]
        profile = json.loads(provider[0]["config"]["kc.user.profile.config"][0])
        username = next(
            attribute
            for attribute in profile["attributes"]
            if attribute["name"] == "username"
        )
        pattern = re.compile(username["validations"]["pattern"]["pattern"])
        self.assertTrue(pattern.match("alice19"))
        for refused in ("root", "al0ce", "alice_x", "zoe", "Alice"):
            with self.subTest(username=refused):
                self.assertIsNone(pattern.match(refused))

    def test_realm_is_valid_json_with_one_saml_app(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        clients = {c["clientId"]: c for c in realm["clients"]}
        client = clients[path_join([APP_URL, "saml/metadata"])]
        self.assertEqual(client["protocol"], "saml")
        self.assertEqual(client["redirectUris"], [path_join([APP_URL, "saml/acs"])])

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


if __name__ == "__main__":
    unittest.main()
