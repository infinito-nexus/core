"""Whether Roundcube forces https on its generated URLs, per canonical scheme.

Roundcube derives the OAuth ``redirect_uri`` from the request scheme, and the
reverse proxy speaks plain HTTP to the container. Forcing https is therefore
right on a clearnet vhost and wrong on an onion one, which is served over HTTP
because Tor carries the encryption. Getting it wrong is not cosmetic: Keycloak
compares the ``redirect_uri`` against the client's registered list verbatim and
answers "Invalid parameter: redirect_uri" on a scheme mismatch, so the webmail
login dies before the form is ever drawn.

Both sides are built from ``canonical_url``, so the assertion here is that the
template follows that one source rather than a hard-coded scheme.
"""

from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined

from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = (
    PROJECT_ROOT
    / "roles"
    / "web-app-stalwart"
    / "templates"
    / "roundcube-oauth.inc.php.j2"
)
FORCE_HTTPS = "$_SERVER['HTTPS'] = 'on';"
ONION_BASE = (
    "http://webmail.4dl6yijmuksgh5bfaf3csqoelji7zptyuo6wy5g5prjpnk6vdbzfwnad.onion"
)
CLEARNET_BASE = "https://webmail.infinito.example"


def _render(base_url: str, *, sso_enabled: bool = True, socks_proxy: str = "") -> str:
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - a PHP config file, and Ansible's templar does not escape either
    )
    env.filters["bool"] = bool
    return env.from_string(read_text(TEMPLATE)).render(
        STALWART_SSO_ENABLED=sso_enabled,
        STALWART_WEBMAIL_BASE_URL=base_url,
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


class TestRoundcubeOauthScheme(unittest.TestCase):
    def test_a_clearnet_vhost_still_forces_https(self):
        self.assertIn(FORCE_HTTPS, _render(CLEARNET_BASE))

    def test_an_onion_vhost_is_left_on_http(self):
        self.assertNotIn(FORCE_HTTPS, _render(ONION_BASE))

    def test_the_scheme_is_never_decided_by_the_onion_suffix_alone(self):
        self.assertIn(FORCE_HTTPS, _render("https://webmail.example.onion"))

    def test_an_onion_issuer_routes_the_back_channel_through_tor(self):
        rendered = _render(
            ONION_BASE, socks_proxy="socks5h://host.docker.internal:9050"
        )
        self.assertIn(
            "$config['http_client'] = ['proxy' => 'socks5h://host.docker.internal:9050'];",
            rendered,
        )

    def test_the_proxy_must_hand_the_name_to_tor_to_resolve(self):
        """socks5:// resolves locally, which is what cURL refuses to do for .onion."""
        rendered = _render(
            ONION_BASE, socks_proxy="socks5h://host.docker.internal:9050"
        )
        self.assertNotIn("'proxy' => 'socks5://", rendered)

    def test_a_clearnet_issuer_gets_no_proxy_at_all(self):
        self.assertNotIn("http_client", _render(CLEARNET_BASE))

    def test_nothing_is_emitted_without_sso(self):
        rendered = _render(
            CLEARNET_BASE, sso_enabled=False, socks_proxy="socks5h://tor:9050"
        )
        self.assertNotIn(FORCE_HTTPS, rendered)
        self.assertNotIn("oauth_client_id", rendered)
        self.assertNotIn("http_client", rendered)


if __name__ == "__main__":
    unittest.main()
