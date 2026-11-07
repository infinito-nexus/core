from __future__ import annotations

import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.cookie_scope import FilterModule as CookieScopeFilters
from plugins.filter.network_of import FilterModule as NetworkFilters
from utils.roles.applications.services.sso import (
    SsoConfigConflictError,
    get_sso_config,
)

from . import PROJECT_ROOT

TEMPLATE = "roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2"
APP = "web-app-x"
DOMAIN = "x.example.org"
DOMAIN_PRIMARY = "example.org"
CLAIM = "groups"
GROUP = "roles/web-app-x/administrator"
OIDC = {
    "CLIENT": {
        "SECRET": "placeholder-client-secret",
        "ID": "infinito",
        "ISSUER_URL": "https://auth.example.org/realms/main",
        "AUTHORIZE_URL": "https://auth.example.org/realms/main/auth",
        "TOKEN_URL": "https://auth.example.org/realms/main/token",
        "CERTS": "https://auth.example.org/realms/main/certs",
    },
    "BUTTON_TEXT": "Sign in",
}
GROUP_ADMISSION = (
    f'scope                   =   "openid email profile {CLAIM}"\n'
    f'oidc_groups_claim       =   "{CLAIM}"\n'
    f'allowed_groups          =   ["/{GROUP}"]\n'
    'email_domains           =   ["*"]\n'
)
OPEN_ADMISSION = (
    f'scope                   =   "openid email profile {CLAIM}"\n'
    f'oidc_groups_claim       =   "{CLAIM}"\n'
    'email_domains           =   ["*"]\n'
)
DOMAIN_ADMISSION = f'\nemail_domains           =   "{DOMAIN_PRIMARY}"\n\n'


def applications(**oauth2) -> dict:
    """Return a payload whose ``web-app-x`` is gated by oauth2-proxy.

    Args:
        oauth2: ``services.sso.oauth2`` keys besides ``origin``.
    """
    return {
        APP: {
            "services": {
                "sso": {
                    "enabled": True,
                    "flavor": "oauth2",
                    "oauth2": {
                        "origin": {"host": "application", "port": "8080"},
                        **oauth2,
                    },
                }
            }
        }
    }


def stub_lookup(apps: dict):
    """Return a `lookup` that answers `sso` through the real resolver.

    Args:
        apps: the merged applications payload `lookup('sso')` resolves against.
    """
    config = {
        "services.sso_proxy.ports.internal.http": 4180,
        "secrets.credentials.sso_proxy_cookie_secret": "placeholder-cookie",
    }
    tls = {"enabled": True, "protocols.web": "https"}

    def lookup(kind, *args, **_kwargs):
        if kind == "sso":
            return get_sso_config(apps, args[0])[args[1]]
        if kind == "config":
            return config[args[1]]
        if kind == "domains":
            return [DOMAIN]
        if kind == "tls":
            return tls[args[1]]
        if kind == "sso_cookie_domains":
            return []
        if kind == "sso_whitelist_domains":
            return [DOMAIN]
        if kind == "engine":
            return "redis://redis:6379"
        raise AssertionError(f"unexpected lookup({kind!r}, ...)")

    return lookup


def render(apps: dict) -> str:
    """Render the oauth2-proxy config of ``web-app-x``.

    Args:
        apps: the merged applications payload.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    core = CoreFilters().filters()
    env.filters.update({name: core[name] for name in ("regex_replace", "to_json")})
    for filters in (CookieScopeFilters, NetworkFilters):
        env.filters.update(filters().filters())
    return env.get_template(TEMPLATE).render(
        lookup=stub_lookup(apps),
        sso_proxy_application_id=APP,
        sso_proxy_network="clearnet",
        DEPLOYMENT_MODE="compose",
        TLS_MODE="letsencrypt",
        DOMAIN_PRIMARY=DOMAIN_PRIMARY,
        RBAC={"GROUP": {"CLAIM": CLAIM}},
        OIDC=OIDC,
    )


def settings(rendered: str) -> dict[str, str]:
    """Return ``{key: value}`` for every ``key = value`` line.

    Args:
        rendered: the rendered config.
    """
    pairs = (line.partition("=") for line in rendered.splitlines())
    return {key.strip(): value.strip() for key, sep, value in pairs if sep}


class TestAllowedGroups(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = render(applications(allowed_groups=[GROUP]))

    def test_the_admission_block_is_unchanged(self) -> None:
        self.assertIn(GROUP_ADMISSION, self.rendered)

    def test_only_the_listed_groups_are_admitted(self) -> None:
        self.assertEqual(settings(self.rendered)["allowed_groups"], f'["/{GROUP}"]')


class TestAllowAllUsers(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = render(applications(allow_all_users=True))
        self.settings = settings(self.rendered)

    def test_the_admission_block_requests_groups_without_restricting(self) -> None:
        self.assertIn(OPEN_ADMISSION, self.rendered)

    def test_no_group_restriction_is_rendered(self) -> None:
        self.assertNotIn("allowed_groups", self.settings)

    def test_the_groups_claim_is_still_forwarded(self) -> None:
        self.assertEqual(
            (self.settings["scope"], self.settings["oidc_groups_claim"]),
            (f'"openid email profile {CLAIM}"', f'"{CLAIM}"'),
        )

    def test_external_email_domains_are_admitted(self) -> None:
        self.assertEqual(self.settings["email_domains"], '["*"]')

    def test_an_inventory_cleared_group_list_admits_everyone(self) -> None:
        self.assertEqual(
            render(applications(allowed_groups=[], allow_all_users=True)),
            self.rendered,
        )


class TestNeitherKey(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = render(applications())

    def test_only_the_primary_domain_is_admitted(self) -> None:
        self.assertIn(DOMAIN_ADMISSION, self.rendered)

    def test_no_groups_claim_is_requested(self) -> None:
        self.assertEqual(
            {"scope", "oidc_groups_claim", "allowed_groups"}
            & set(settings(self.rendered)),
            set(),
        )

    def test_a_false_allow_all_users_renders_the_same(self) -> None:
        self.assertEqual(render(applications(allow_all_users=False)), self.rendered)


class TestConflict(unittest.TestCase):
    def test_allow_all_users_with_allowed_groups_fails_the_render(self) -> None:
        with self.assertRaises(SsoConfigConflictError) as ctx:
            render(applications(allowed_groups=[GROUP], allow_all_users=True))
        for name in (
            APP,
            "services.sso.oauth2.allow_all_users",
            "services.sso.oauth2.allowed_groups",
        ):
            with self.subTest(name=name):
                self.assertIn(name, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
