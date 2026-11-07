from __future__ import annotations

import json
import re
import unittest
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

CASC = "roles/web-app-jenkins/templates/casc.yaml.j2"
KEYCLOAK_CLIENT = "roles/web-app-keycloak/templates/import/clients/default.json.j2"
OIDC = {
    "CLIENT": {
        "ID": "infinito.nexus",
        "SECRET": "secret",
        "DISCOVERY_DOCUMENT": "https://auth.example.org/realms/infinito.nexus/.well-known/openid-configuration",
    },
    "ATTRIBUTES": {"USERNAME": "preferred_username"},
}


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    return env


def requested_scopes() -> list[str]:
    administrator = SimpleNamespace(username="administrator", password="secret")

    def lookup(kind, *_args, **_kw):
        if kind == "users":
            return administrator
        if kind == "tls":
            return "https://jenkins.example.org/"
        raise AssertionError(f"unexpected lookup {kind!r}")

    rendered = (
        environment()
        .get_template(CASC)
        .render(
            SOFTWARE_NAME="Infinito.Nexus",
            JENKINS_OIDC_ENABLED=True,
            JENKINS_LDAP_ENABLED=False,
            OIDC=OIDC,
            application_id="web-app-jenkins",
            lookup=lookup,
        )
    )
    well_known = load_yaml_str(rendered)["jenkins"]["securityRealm"]["oic"][
        "serverConfiguration"
    ]["wellKnown"]
    return well_known["scopesOverride"].split()


def client_scopes() -> set[str]:
    def lookup(kind, _app, key):
        if kind != "config":
            raise AssertionError(f"unexpected lookup {kind!r}")
        return key.rsplit(".", 1)[-1]

    rendered = (
        environment()
        .get_template(KEYCLOAK_CLIENT)
        .render(
            KEYCLOAK_CLIENT_ID="infinito.nexus",
            KEYCLOAK_REALM_URL="https://auth.example.org/realms/infinito.nexus",
            OIDC=OIDC,
            KEYCLOAK_REDIRECT_URIS=[],
            KEYCLOAK_WEB_ORIGINS=[],
            KEYCLOAK_FRONTCHANNEL_LOGOUT_URL="",
            KEYCLOAK_POST_LOGOUT_URIS="",
            KEYCLOAK_RBAC_GROUP_CLAIM="groups",
            KEYCLOAK_MOODLE_ENABLED=False,
            application_id="web-app-keycloak",
            lookup=lookup,
        )
    )
    client = json.loads(rendered)
    return set(client["defaultClientScopes"]) | set(client["optionalClientScopes"])


class TestOidcScopes(unittest.TestCase):
    def test_jenkins_asks_for_identity_scopes_only(self) -> None:
        self.assertEqual(requested_scopes(), ["openid", "profile", "email"])

    def test_every_requested_scope_is_one_the_client_carries(self) -> None:
        self.assertLessEqual(set(requested_scopes()), client_scopes())


if __name__ == "__main__":
    unittest.main()
