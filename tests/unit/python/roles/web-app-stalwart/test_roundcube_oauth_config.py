"""Which OAuth settings the Roundcube include emits, per SSO state and issuer network."""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = (
    PROJECT_ROOT
    / "roles"
    / "web-app-stalwart"
    / "templates"
    / "roundcube-oauth.inc.php.j2"
)


def _render(*, sso_enabled: bool = True, socks_proxy: str = "") -> str:
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    return env.from_string(read_text(TEMPLATE)).render(
        STALWART_SSO_ENABLED=sso_enabled,
        STALWART_OIDC_SOCKS_PROXY=socks_proxy,
        STALWART_WEBMAIL_OIDC_CLIENT_ID="roundcube",
        OIDC={
            "BUTTON_TEXT": "Sign in",
            "ATTRIBUTES": {"USERNAME": "preferred_username"},
            "CLIENT": {
                "AUTHORIZE_URL": "https://auth.infinito.example/auth",
                "TOKEN_URL": "https://auth.infinito.example/token",
                "USER_INFO_URL": "https://auth.infinito.example/userinfo",
                "LOGOUT_URL": "https://auth.infinito.example/logout",
            },
        },
    )


class TestRoundcubeOauthConfig(unittest.TestCase):
    def test_an_onion_issuer_routes_the_back_channel_through_tor(self):
        rendered = _render(socks_proxy="socks5h://host.docker.internal:9050")
        self.assertIn(
            "$config['http_client'] = ['proxy' => 'socks5h://host.docker.internal:9050'];",
            rendered,
        )

    def test_the_proxy_must_hand_the_name_to_tor_to_resolve(self):
        """socks5:// resolves locally, which is what cURL refuses to do for .onion."""
        rendered = _render(socks_proxy="socks5h://host.docker.internal:9050")
        self.assertNotIn("'proxy' => 'socks5://", rendered)

    def test_a_clearnet_issuer_gets_no_proxy_at_all(self):
        self.assertNotIn("http_client", _render())

    def test_nothing_is_emitted_without_sso(self):
        rendered = _render(sso_enabled=False, socks_proxy="socks5h://tor:9050")
        self.assertNotIn("$_SERVER['HTTPS']", rendered)
        self.assertNotIn("oauth_client_id", rendered)
        self.assertNotIn("http_client", rendered)


if __name__ == "__main__":
    unittest.main()
