from __future__ import annotations

import json
import re
import unittest
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT
from .test_realm_import_json import CONTEXT, render

if TYPE_CHECKING:
    from pathlib import Path

CLIENT_TEMPLATES = sorted(
    PROJECT_ROOT.glob("roles/*/templates/keycloak/clients.json.j2")
)
BACKCHANNEL_LOGOUT_URL = "backchannel.logout.url"
ONION = "a" * 56 + ".onion"
SHARED_CLIENT_ID = CONTEXT["KEYCLOAK_CLIENT_ID"]


def role_config(role: str, path: str):
    """Resolve ``lookup('config', role, path)`` for a ``services.*`` path.

    Args:
        role: role directory name.
        path: dotted path below the role's config, starting with ``services.``.
    """
    head, _, rest = path.partition(".")
    if head != "services":
        raise AssertionError(f"unexpected config path {path!r} for {role}")
    node = load_yaml_any(str(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_SERVICES))
    for key in rest.split("."):
        node = node[key]
    return node


def canonical_origin(app: str, key: str = "") -> str:
    """The clearnet origin the stub serves an application, or one canonical of it.

    Args:
        app: application id.
        key: named canonical domain, empty for the primary one.
    """
    return f"https://{key + '.' if key else ''}{app}.example.com"


def onion_sibling(url: str) -> list[str]:
    """
    Args:
        url: the URL lookup('network_urls') is asked for.

    Returns:
        The URL on the clearnet and on its onion sibling, canonical network first.
    """
    parts = urlsplit(url)
    onion = parts.netloc.removesuffix(".example.com") + "." + ONION
    return [url, f"http://{onion}{parts.path}"]


def lookup(name, *args, **_kwargs):
    """Stub the lookups an application's client fragment performs.

    Args:
        name: the lookup plugin the template asked for.
    """
    if name == "config":
        return role_config(*args)
    if name == "canonical_url":
        return canonical_origin(*args)
    if name == "tls":
        return canonical_origin(args[0])
    if name == "network_urls":
        return onion_sibling(args[0])
    raise AssertionError(f"unexpected lookup {name}{args}")


def render_fragment(template: Path) -> list[dict]:
    """Render one ``templates/keycloak/clients.json.j2`` the way the realm includes it.

    Args:
        template: the fragment's path.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    source = env.get_template(str(template.relative_to(PROJECT_ROOT))).render(
        lookup=lookup, **CONTEXT
    )
    return json.loads(f"[{source}]")


def backchannel_findings(client: dict) -> list[str]:
    """What keeps one back-channel client from ending sessions safely and on every network.

    Args:
        client: a client representation that carries a back-channel logout URL.
    """
    attributes = client["attributes"]
    url = urlsplit(attributes[BACKCHANNEL_LOGOUT_URL])
    origin = f"{url.scheme}://{url.netloc}"
    findings = []
    if client["frontchannelLogout"] is not False:
        findings.append("frontchannelLogout is not false")
    if client["serviceAccountsEnabled"] is not False:
        findings.append("serviceAccountsEnabled is not false")
    if attributes.get("backchannel.logout.session.required") != "true":
        findings.append("backchannel.logout.session.required is not 'true'")
    if not client["webOrigins"] or client["webOrigins"][0] != origin:
        findings.append(f"{origin} is not the canonical origin {client['webOrigins']}")
    findings.extend(
        f"no redirect URI on the network sibling {sibling}"
        for sibling in onion_sibling(origin)
        if not any(uri.startswith(sibling + "/") for uri in client["redirectUris"])
    )
    return findings


def shared_client_findings(client: dict) -> list[str]:
    """What turns the shared client away from the front-channel sweep per network.

    Args:
        client: the shared client's representation.
    """
    attributes = client["attributes"]
    findings = []
    if BACKCHANNEL_LOGOUT_URL in attributes:
        findings.append("the shared client carries a back-channel logout URL")
    if client["frontchannelLogout"] is not True:
        findings.append("frontchannelLogout is not true")
    if (
        attributes.get("frontchannel.logout.url")
        != CONTEXT["KEYCLOAK_FRONTCHANNEL_LOGOUT_URL"]
    ):
        findings.append("the conductor is not the front-channel logout URL")
    if attributes.get("frontchannel.logout.session.required") != "true":
        findings.append("frontchannel.logout.session.required is not 'true'")
    return findings


def shared_client() -> dict:
    realm = json.loads(render([]))
    return next(c for c in realm["clients"] if c["clientId"] == SHARED_CLIENT_ID)


class TestBackchannelClients(unittest.TestCase):
    def setUp(self) -> None:
        self.clients = {
            template: render_fragment(template) for template in CLIENT_TEMPLATES
        }
        self.backchannel = [
            client
            for clients in self.clients.values()
            for client in clients
            if BACKCHANNEL_LOGOUT_URL in client["attributes"]
        ]

    def test_matrix_ships_a_backchannel_client(self) -> None:
        templates = {
            template.parts[-4]
            for template, clients in self.clients.items()
            if any(BACKCHANNEL_LOGOUT_URL in c["attributes"] for c in clients)
        }
        self.assertIn("web-app-matrix", templates)

    def test_every_backchannel_client_is_safe_and_reaches_every_network(self) -> None:
        self.assertTrue(self.backchannel)
        for client in self.backchannel:
            with self.subTest(client=client["clientId"]):
                self.assertEqual(backchannel_findings(client), [])

    def test_no_client_of_an_application_runs_a_service_account(self) -> None:
        for clients in self.clients.values():
            for client in clients:
                with self.subTest(client=client["clientId"]):
                    self.assertIs(client["serviceAccountsEnabled"], False)

    def test_a_confidential_client_reuses_the_shared_secret(self) -> None:
        for client in self.backchannel:
            with self.subTest(client=client["clientId"]):
                self.assertFalse(client["publicClient"])
                self.assertEqual(client["secret"], CONTEXT["OIDC"]["CLIENT"]["SECRET"])

    def test_the_matrix_client_logs_out_on_the_synapse_origin(self) -> None:
        client = next(
            c
            for clients in self.clients.values()
            for c in clients
            if c["clientId"]
            == role_config("web-app-matrix", "services.sso.oidc.clients.synapse")
        )
        self.assertEqual(
            client["attributes"][BACKCHANNEL_LOGOUT_URL],
            canonical_origin("web-app-matrix", "synapse")
            + "/_synapse/client/oidc/backchannel_logout",
            "Synapse receives logout tokens on this path of its own origin",
        )

    def test_a_frontchannel_client_fails_the_backchannel_check(self) -> None:
        client = {
            **self.backchannel[0],
            "frontchannelLogout": True,
            "serviceAccountsEnabled": True,
        }
        self.assertEqual(len(backchannel_findings(client)), 2)


class TestSharedClientStaysOnTheSweep(unittest.TestCase):
    def test_the_shared_client_keeps_the_sweep_per_network(self) -> None:
        self.assertEqual(shared_client_findings(shared_client()), [])

    def test_a_backchannel_url_on_the_shared_client_fails_the_check(self) -> None:
        client = shared_client()
        client["attributes"][BACKCHANNEL_LOGOUT_URL] = "https://shared.example.com/"
        self.assertEqual(
            shared_client_findings(client),
            ["the shared client carries a back-channel logout URL"],
        )


if __name__ == "__main__":
    unittest.main()
