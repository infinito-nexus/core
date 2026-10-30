from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.network_of import network_of
from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = PROJECT_ROOT / "roles/sys-front-inj-logout/templates/logout_one_liner.js.j2"
ONION = "a" * 56 + ".onion"
LOGOUT_URL = "https://auth.example/realms/example/protocol/openid-connect/logout"
CONDUCTORS = {"clearnet": "https://logout.example/", "tor": f"http://logout.{ONION}/"}


def logout_target(domain: str, canonical: str, **extra) -> str:
    def lookup(name, *terms):
        if name == "domain":
            return canonical
        if name == "tls" and terms == ("web-svc-logout", "url.base"):
            return CONDUCTORS[network_of(domain)]
        raise AssertionError(f"unexpected lookup: {name!r} {terms!r}")

    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["network_of"] = network_of
    rendered = env.from_string(read_text(str(TEMPLATE))).render(
        lookup=lookup,
        domain=domain,
        application_id="web-app-nextcloud",
        MODE_DEBUG=False,
        OIDC={"CLIENT": {"LOGOUT_URL": LOGOUT_URL, "ID": "example"}},
        **extra,
    )
    return rendered.split("initLogoutPatch(")[1].split("'")[1]


class TestLogoutOneLiner(unittest.TestCase):
    def test_the_canonical_vhost_keeps_the_bare_issuer_logout(self):
        self.assertEqual(
            logout_target("next.cloud.example", "next.cloud.example"), LOGOUT_URL
        )

    def test_the_onion_vhost_returns_to_the_onion_conductor(self):
        target = urlsplit(logout_target(f"next.cloud.{ONION}", "next.cloud.example"))
        self.assertEqual(f"{target.scheme}://{target.netloc}{target.path}", LOGOUT_URL)
        self.assertEqual(
            parse_qs(target.query),
            {
                "client_id": ["example"],
                "post_logout_redirect_uri": [CONDUCTORS["tor"]],
            },
        )

    def test_an_onion_only_node_keeps_the_bare_issuer_logout(self):
        self.assertEqual(
            logout_target(f"next.cloud.{ONION}", f"next.cloud.{ONION}"), LOGOUT_URL
        )

    def test_an_external_issuer_keeps_the_bare_logout(self):
        self.assertEqual(
            logout_target(
                f"next.cloud.{ONION}",
                "next.cloud.example",
                OIDC_OVERRIDE={"URL": "https://idp.example"},
            ),
            LOGOUT_URL,
        )


if __name__ == "__main__":
    unittest.main()
