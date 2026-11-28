from __future__ import annotations

import json
import re
import unittest
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.url.join import url_join
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

APP = "web-app-openwebui"
ROLE = PROJECT_ROOT / "roles" / APP
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
OIDC_VARS = load_yaml_str(
    read_text(str(PROJECT_ROOT / "group_vars" / "all" / "11_oidc.yml"))
)
CLIENT_TEMPLATE = f"roles/{APP}/templates/keycloak/clients.json.j2"
CLIENT_ID = SERVICES["sso"]["oidc"]["clients"]["web"]
KEYCLOAK_END_SESSION_PATH = "/protocol/openid-connect/logout"
SIGN_IN_PAGE = "auth"
ONION = "a" * 56 + ".onion"
NETWORKS = {
    "tor": {
        "issuer": f"http://auth.{ONION}/realms/infinito.nexus",
        "openwebui": f"http://chat.ai.{ONION}/",
    },
    "clearnet": {
        "issuer": "https://auth.infinito.example/realms/infinito.nexus",
        "openwebui": "https://chat.ai.infinito.example/",
    },
}


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    env.filters["url_join"] = url_join
    env.filters["to_json"] = json.dumps
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, str(value)
    )
    return env


def end_session_url(network: str) -> str:
    """
    Args:
        network: key of ``NETWORKS`` that serves Keycloak and Open WebUI.

    Returns:
        What ``OPENWEBUI_OIDC_END_SESSION_URL`` of vars/main.yml renders to,
        with ``OIDC.CLIENT.LOGOUT_URL`` rendered from group_vars.
    """
    env = _environment()
    protocol = env.from_string(OIDC_VARS["_oidc_protocol_oidc"]).render(
        _oidc_client_issuer_url=NETWORKS[network]["issuer"]
    )
    logout = env.from_string(OIDC_VARS["defaults_oidc"]["CLIENT"]["LOGOUT_URL"]).render(
        _oidc_protocol_oidc=protocol
    )
    return env.from_string(VARS["OPENWEBUI_OIDC_END_SESSION_URL"]).render(
        OIDC={"CLIENT": {"LOGOUT_URL": logout}},
        OPENWEBUI_OIDC_CLIENT_ID=CLIENT_ID,
        OPENWEBUI_URL=NETWORKS[network]["openwebui"],
    )


def post_logout_patterns(network: str) -> list[str]:
    """
    Args:
        network: key of ``NETWORKS`` the canonical Open WebUI is served on;
            the other network serves its sibling.

    Returns:
        The ``post.logout.redirect.uris`` of the role's Keycloak client.
    """
    canonical = NETWORKS[network]["openwebui"].rstrip("/")
    origins = [canonical] + [
        urls["openwebui"].rstrip("/")
        for key, urls in NETWORKS.items()
        if key != network
    ]

    def lookup(name: str, *terms: str):
        if name == "tls" and terms == (APP, "url.origin"):
            return canonical
        if name == "network_urls" and terms == (canonical,):
            return origins
        if name == "config" and terms[0] == APP and terms[1].startswith("services."):
            node = SERVICES
            for key in terms[1].removeprefix("services.").split("."):
                node = node[key]
            return node
        raise AssertionError(
            f"the client fragment renders an unexpected lookup {name}{terms}"
        )

    client = json.loads(
        _environment()
        .get_template(CLIENT_TEMPLATE)
        .render(lookup=lookup, KEYCLOAK_RBAC_GROUP_CLAIM="groups")
    )
    return client["attributes"]["post.logout.redirect.uris"].split("##")


def keycloak_accepts(patterns: list[str], uri: str) -> bool:
    """
    Args:
        patterns: valid post-logout redirect URIs of a Keycloak client.
        uri: the ``post_logout_redirect_uri`` a logout request carries.

    Returns:
        Whether Keycloak's redirect check, a prefix match for a pattern that
        ends in ``*`` and an exact match otherwise, lets ``uri`` through.
    """
    return any(
        uri.startswith(pattern[:-1]) if pattern.endswith("*") else uri == pattern
        for pattern in patterns
    )


class TestOpenWebuiSignOutEndsTheKeycloakSession(unittest.TestCase):
    def test_sign_out_targets_the_keycloak_end_session_endpoint_on_every_network(
        self,
    ) -> None:
        for network, urls in NETWORKS.items():
            with self.subTest(network=network):
                parts = urlsplit(end_session_url(network))
                self.assertEqual(
                    f"{parts.scheme}://{parts.netloc}{parts.path}",
                    urls["issuer"] + KEYCLOAK_END_SESSION_PATH,
                    "Open WebUI discovers this endpoint itself through aiohttp, whose "
                    "c-ares resolver refuses an .onion issuer under RFC 7686, so the "
                    "sign-out answered 500 and left the Keycloak session open",
                )

    def test_sign_out_names_the_client_and_returns_to_the_sign_in_page(self) -> None:
        for network, urls in NETWORKS.items():
            with self.subTest(network=network):
                self.assertEqual(
                    parse_qs(
                        urlsplit(end_session_url(network)).query, strict_parsing=True
                    ),
                    {
                        "client_id": [CLIENT_ID],
                        "post_logout_redirect_uri": [urls["openwebui"] + SIGN_IN_PAGE],
                    },
                    "Keycloak checks post_logout_redirect_uri against the client "
                    "client_id names, and no id_token_hint may ride in the URL",
                )

    def test_keycloak_accepts_the_post_logout_redirect_on_every_network(self) -> None:
        for network in NETWORKS:
            with self.subTest(network=network):
                redirect = parse_qs(urlsplit(end_session_url(network)).query)[
                    "post_logout_redirect_uri"
                ][0]
                patterns = post_logout_patterns(network)
                self.assertTrue(
                    keycloak_accepts(patterns, redirect),
                    f"Keycloak refuses {redirect}, the client allows only {patterns}",
                )

    def test_keycloak_refuses_a_post_logout_redirect_off_the_open_webui_origins(
        self,
    ) -> None:
        for network in NETWORKS:
            with self.subTest(network=network):
                self.assertFalse(
                    keycloak_accepts(
                        post_logout_patterns(network),
                        "https://dashboard.infinito.example/auth",
                    )
                )


if __name__ == "__main__":
    unittest.main()
