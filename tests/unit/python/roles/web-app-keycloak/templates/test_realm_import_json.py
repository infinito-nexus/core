from __future__ import annotations

import importlib.util
import json
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
IMPORT_DIR = ROLE_DIR / "templates/import"


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
    "KEYCLOAK_LDAP_USER_OBJECT_CLASSES": "inetOrgPerson, organizationalPerson",
    "KEYCLOAK_LDAP_CMP_NAME": "ldap",
    "KEYCLOAK_LDAP_URL": "ldap://openldap:389",
    "KEYCLOAK_LDAP_BIND_DN": "cn=admin,dc=example,dc=com",
    "KEYCLOAK_LDAP_BIND_PW": "secret",
    "KEYCLOAK_LDAP_CONNECTION_POOLING": "true",
    "KEYCLOAK_LDAP_SYNC_CHANGES_PERIOD": "86400",
    "KEYCLOAK_LDAP_SYNC_FULL_PERIOD": "604800",
    "KEYCLOAK_RBAC_GROUP_NAME": "groups",
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
        "RBAC": {"FLAVORS": ["groupOfNames"]},
        "USER": {
            "ATTRIBUTES": {
                "ID": "uid",
                "MAIL": "mail",
                "FULLNAME": "cn",
                "FIRSTNAME": "givenName",
                "SURNAME": "sn",
                "NEXTCLOUD_QUOTA": "nextcloudQuota",
                "SSH_PUBLIC_KEY": "sshPublicKey",
            }
        },
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
    return APP_URL


def render(saml_apps: list[str]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(IMPORT_DIR)),
        trim_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - renders JSON, where HTML escaping corrupts the value
    )
    env.filters["path_join"] = path_join
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = bool
    env.filters.update(role_filters())
    return env.get_template("realm.json.j2").render(
        KEYCLOAK_SAML_APPS=saml_apps,
        lookup=fake_lookup,
        application_id="web-app-keycloak",
        DOMAIN_PRIMARY="example.com",
        **CONTEXT,
    )


class TestRealmImportJson(unittest.TestCase):
    def test_realm_is_valid_json_without_saml_apps(self) -> None:
        realm = json.loads(render([]))
        client_ids = [c["clientId"] for c in realm["clients"]]
        self.assertNotIn(path_join([APP_URL, "saml/metadata"]), client_ids)

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

    def test_saml_client_omits_the_role_list_scope(self) -> None:
        realm = json.loads(render(["web-app-suitecrm"]))
        client = next(c for c in realm["clients"] if c.get("protocol") == "saml")
        self.assertEqual(client["defaultClientScopes"], [])

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
