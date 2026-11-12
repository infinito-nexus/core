"""Semaphore signs a browser in on the network sibling it was opened on.

Semaphore builds every post-login redirect from its single ``SEMAPHORE_WEB_ROOT``,
marks the ``semaphore`` session cookie ``Secure`` when that root is https, and
sends Keycloak the ``redirect_url`` of the provider the button names. With one
clearnet provider, a login started on the onion sibling set its ``oauthstate``
cookie on the onion host and came back to the clearnet callback without it.

A node serving the role on clearnet and Tor therefore gets a second provider
whose callback is the onion sibling, every vhost lists only its own provider,
and the onion vhost keeps redirects on its host and drops ``Secure`` from the
session cookie. A node without an onion sibling renders what it rendered
before. The real ``vars/main.yml`` is resolved by Ansible's templar with the
real ``tls`` lookup and the site lookups stubbed.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

ROLE = "web-app-semaphore"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
CORE = ROLE_DIR / "tasks" / "00_core.yml"
HTML_LOCATION = "roles/sys-svc-proxy/templates/location/html.conf.j2"

CLEAR = "semaphore.example.test"
ONION = "semaphore." + "a" * 56 + ".onion"
ISSUER = "https://auth.example.test/realms/main"
SECRET = "placeholder-client-secret"
BUTTON = "Sign in with Keycloak"

OIDC = {
    "CLIENT": {"ISSUER_URL": ISSUER, "ID": "semaphore-client", "SECRET": SECRET},
    "ATTRIBUTES": {"USERNAME": "preferred_username"},
}

SINGLE_PROVIDER_JSON = (
    '{"keycloak": {"display_name": "Sign in with Keycloak", '
    f'"provider_url": "{ISSUER}", "client_id": "semaphore-client", '
    f'"client_secret": "{SECRET}", '
    f'"redirect_url": "https://{CLEAR}/api/auth/oidc/keycloak/redirect", '
    '"username_claim": "preferred_username", "email_claim": "email", '
    '"name_claim": "name", "scopes": ["openid", "profile", "email"]}}'
)

LISTED = {
    provider: f'{{"id":"{provider}","name":"{BUTTON}","color":"","icon":""}}'
    for provider in ("keycloak", "keycloak_onion")
}

VHOST = ("SEMAPHORE_LOCATION_CONFIGURATION", "SEMAPHORE_OIDC_LOGIN_LOCATION")
ORDERS = (("keycloak", "keycloak_onion"), ("keycloak_onion", "keycloak"))


def login_metadata(*providers: str) -> str:
    """Return the body Semaphore answers ``GET /api/auth/login`` with.

    Args:
        providers: provider ids in the order Semaphore lists them; its
            ``loginMetadataOidcProvider`` struct serializes id, name, color
            and icon in that order, and ``json.Encoder`` ends with a newline.
    """
    listed = ",".join(LISTED[provider] for provider in providers)
    return (
        '{"oidc_providers":[' + listed + "],"
        '"login_with_password":true,"auth_methods":{}}\n'
    )


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms, **kwargs)]


def _rendered_location(src, template_vars):
    return json.dumps({"src": src, **template_vars})


def resolve(names, *, siblings, domain, canonical=CLEAR, sso=True) -> dict:
    """Resolve role variables for one vhost of one node.

    Args:
        names: the variables of ``vars/main.yml`` to resolve.
        siblings: what ``lookup('network_siblings', canonical)`` answers.
        domain: the vhost being rendered.
        canonical: what ``lookup('domain', application_id)`` answers.
        sso: what ``services.sso.enabled`` answers.

    Returns:
        ``{name: value}``; the html location template lookup answers its
        source and ``template_vars`` as JSON instead of rendering.
    """
    variables = {
        "domain": domain,
        "OIDC": OIDC,
        "TLS_ENABLED": True,
        "TLS_MODE": "letsencrypt",
    }
    stubs = {
        "domain": lambda _app: canonical,
        "network_siblings": lambda _domain: siblings,
        "config": lambda _app, path: {"services.sso.enabled": sso}[path],
        "path_absolute": lambda path: path,
        "ansible.builtin.template": _rendered_location,
        "domains": lambda: {ROLE: siblings},
        "applications": lambda: {ROLE: {}},
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "tls":
            tls = TlsLookup()
            tls._loader = kwargs.get("loader")
            tls._templar = None
            return tls
        if name in stubs:
            return _Stub(stubs[name])
        return real_get(name, *args, **kwargs)

    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**declared, **variables})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return {name: templar.template(declared[name]) for name in names}


def filtered(body: str, configuration: str) -> dict:
    """Apply the ``sub_filter`` lines of a location to a response body.

    Args:
        body: the upstream response.
        configuration: the location's extra directives.

    Returns:
        The rewritten body, parsed as the browser parses it.
    """
    for raw in configuration.splitlines():
        line = raw.strip()
        if not line.startswith("sub_filter '"):
            continue
        pattern, _, replacement = line[len("sub_filter '") :].rpartition("' '")
        body = body.replace(pattern, replacement.rstrip("';"), 1)
    return json.loads(body)


class TestOnionSiblingGetsItsOwnProvider(unittest.TestCase):
    def providers(self) -> dict:
        rendered = resolve(
            ["SEMAPHORE_OIDC_PROVIDERS_JSON"], siblings=[CLEAR, ONION], domain=CLEAR
        )
        return json.loads(rendered["SEMAPHORE_OIDC_PROVIDERS_JSON"])

    def test_both_networks_have_a_provider(self) -> None:
        self.assertEqual(sorted(self.providers()), ["keycloak", "keycloak_onion"])

    def test_the_onion_callback_is_plaintext_on_the_onion_sibling(self) -> None:
        self.assertEqual(
            self.providers()["keycloak_onion"]["redirect_url"],
            f"http://{ONION}/api/auth/oidc/keycloak_onion/redirect",
        )

    def test_the_clearnet_callback_is_unchanged(self) -> None:
        self.assertEqual(
            self.providers()["keycloak"]["redirect_url"],
            f"https://{CLEAR}/api/auth/oidc/keycloak/redirect",
        )

    def test_the_providers_differ_only_in_their_callback(self) -> None:
        providers = self.providers()
        clear, onion = dict(providers["keycloak"]), dict(providers["keycloak_onion"])
        clear.pop("redirect_url")
        onion.pop("redirect_url")
        self.assertEqual(clear, onion)
        self.assertEqual(onion["display_name"], BUTTON)


class TestOnionVhost(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = resolve(VHOST, siblings=[CLEAR, ONION], domain=ONION)
        self.login = json.loads(self.rendered["SEMAPHORE_OIDC_LOGIN_LOCATION"])

    def test_absolute_redirects_stay_on_the_onion_host(self) -> None:
        self.assertIn(
            f"proxy_redirect https://{CLEAR}/ /;",
            self.rendered["SEMAPHORE_LOCATION_CONFIGURATION"].splitlines(),
        )

    def test_the_session_cookie_loses_secure(self) -> None:
        for configuration in (
            self.rendered["SEMAPHORE_LOCATION_CONFIGURATION"],
            self.login["webserver_location_extra_configuration"],
        ):
            self.assertIn(
                "proxy_cookie_flags semaphore nosecure;", configuration.splitlines()
            )

    def test_the_base_href_rewrite_stays(self) -> None:
        self.assertIn(
            f"sub_filter '<base href=\"https://{CLEAR}/\">' '<base href=\"/\">';",
            self.rendered["SEMAPHORE_LOCATION_CONFIGURATION"].splitlines(),
        )

    def test_the_login_metadata_gets_its_own_location(self) -> None:
        self.assertEqual(
            (
                self.login["src"],
                self.login["location"],
                self.login["sso_proxy_enabled"],
            ),
            (HTML_LOCATION, "= /api/auth/login", False),
        )

    def test_the_clearnet_provider_is_dropped_exactly(self) -> None:
        lines = self.login["webserver_location_extra_configuration"].splitlines()
        self.assertIn(f"sub_filter ',{LISTED['keycloak']}' '';", lines)
        self.assertIn(f"sub_filter '{LISTED['keycloak']},' '';", lines)
        self.assertIn("sub_filter_types application/json;", lines)

    def test_only_the_onion_provider_is_listed_in_either_order(self) -> None:
        configuration = self.login["webserver_location_extra_configuration"]
        for order in ORDERS:
            with self.subTest(order=order):
                listed = filtered(login_metadata(*order), configuration)
                self.assertEqual(
                    [p["id"] for p in listed["oidc_providers"]], ["keycloak_onion"]
                )


class TestClearnetVhost(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = resolve(VHOST, siblings=[CLEAR, ONION], domain=CLEAR)
        self.login = json.loads(self.rendered["SEMAPHORE_OIDC_LOGIN_LOCATION"])

    def test_the_location_is_unchanged(self) -> None:
        self.assertEqual(self.rendered["SEMAPHORE_LOCATION_CONFIGURATION"], "")

    def test_the_login_location_only_filters(self) -> None:
        configuration = self.login["webserver_location_extra_configuration"]
        self.assertNotIn("proxy_cookie_flags", configuration)
        self.assertNotIn("proxy_redirect", configuration)

    def test_only_the_clearnet_provider_is_listed_in_either_order(self) -> None:
        configuration = self.login["webserver_location_extra_configuration"]
        for order in ORDERS:
            with self.subTest(order=order):
                listed = filtered(login_metadata(*order), configuration)
                self.assertEqual(
                    [p["id"] for p in listed["oidc_providers"]], ["keycloak"]
                )


class TestWithoutOnionSibling(unittest.TestCase):
    def test_the_single_provider_renders_as_before(self) -> None:
        rendered = resolve(
            ["SEMAPHORE_OIDC_PROVIDERS_JSON"], siblings=[CLEAR], domain=CLEAR
        )
        self.assertEqual(
            rendered["SEMAPHORE_OIDC_PROVIDERS_JSON"], SINGLE_PROVIDER_JSON
        )

    def test_the_vhost_renders_as_before(self) -> None:
        rendered = resolve(VHOST, siblings=[CLEAR], domain=CLEAR)
        self.assertEqual(
            (
                rendered["SEMAPHORE_LOCATION_CONFIGURATION"],
                rendered["SEMAPHORE_OIDC_LOGIN_LOCATION"],
            ),
            ("", ""),
        )

    def test_a_tor_only_node_keeps_one_onion_provider(self) -> None:
        rendered = resolve(
            ["SEMAPHORE_OIDC_PROVIDERS_JSON", *VHOST],
            siblings=[ONION],
            domain=ONION,
            canonical=ONION,
        )
        providers = json.loads(rendered["SEMAPHORE_OIDC_PROVIDERS_JSON"])
        self.assertEqual(
            {name: p["redirect_url"] for name, p in providers.items()},
            {"keycloak": f"http://{ONION}/api/auth/oidc/keycloak/redirect"},
        )
        self.assertEqual(
            (
                rendered["SEMAPHORE_LOCATION_CONFIGURATION"],
                rendered["SEMAPHORE_OIDC_LOGIN_LOCATION"],
            ),
            ("", ""),
        )

    def test_no_sso_means_no_login_filter(self) -> None:
        rendered = resolve(VHOST, siblings=[CLEAR, ONION], domain=ONION, sso=False)
        self.assertEqual(rendered["SEMAPHORE_OIDC_LOGIN_LOCATION"], "")
        self.assertIn(
            "proxy_cookie_flags semaphore nosecure;",
            rendered["SEMAPHORE_LOCATION_CONFIGURATION"].splitlines(),
        )


class TestStackWiring(unittest.TestCase):
    def test_the_proxy_reads_both_vhost_configurations(self) -> None:
        stack = next(
            task
            for task in load_yaml_any(str(CORE))
            if task.get("include_role", {}).get("name") == "sys-stk-full"
        )
        self.assertEqual(
            (
                stack["vars"]["webserver_location_extra_configuration"],
                stack["vars"]["webserver_extra_configuration"],
            ),
            (
                "{{ SEMAPHORE_LOCATION_CONFIGURATION }}",
                "{{ SEMAPHORE_OIDC_LOGIN_LOCATION }}",
            ),
        )


if __name__ == "__main__":
    unittest.main()
