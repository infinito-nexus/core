from __future__ import annotations

import unittest

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.cookie_scope import FilterModule as CookieScopeFilters
from plugins.filter.get.entity_name import FilterModule as EntityNameFilters
from plugins.filter.network_of import FilterModule as NetworkFilters
from plugins.filter.oauth2_claim_headers import FilterModule as ClaimHeaderFilters
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.services.sso import (
    SsoConfigConflictError,
    get_sso_config,
)

from . import PROJECT_ROOT

TEMPLATES = "roles/web-app-keycloak/templates/sso_proxy"
CONFIG_TEMPLATE = f"{TEMPLATES}/oauth2-proxy-keycloak.cfg.j2"
ALPHA_TEMPLATE = f"{TEMPLATES}/oauth2-proxy-keycloak-alpha.yml.j2"
APP = "web-app-x"
DOMAIN = "x.example.org"
DOMAIN_PRIMARY = "example.org"
CLAIM = "groups"
GROUP = "roles/web-app-x/administrator"
GROUP_SCOPE = f"openid email profile {CLAIM}"
PLAIN_SCOPE = "openid email profile"
OIDC = {
    "CLIENT": {
        "SECRET": "placeholder-client-secret",
        "ID": "infinito",
        "ISSUER_URL": "https://auth.example.org/realms/main",
        "AUTHORIZE_URL": "https://auth.example.org/realms/main/auth",
        "TOKEN_URL": "https://auth.example.org/realms/main/token",
        "CERTS": "https://auth.example.org/realms/main/certs",
    },
    "ATTRIBUTES": {"EMAIL": "email"},
    "BUTTON_TEXT": "Sign in",
}
KEYCLOAK_CONFIG = {
    "services.sso_proxy.ports.internal.http": 4180,
    "services.sso_proxy.cookie_refresh": "1m",
    "services.sso_proxy.csrf_cookie_limit": 10,
    "services.sso_proxy.templates_directory": "/templates",
}
OWN_CLIENT_SECRET_PATH = "secrets.credentials.sso_proxy_client_secret"
OWN_CLIENT_SECRET = "placeholder-own-client-secret"
OWN_CLIENT = {"id": "web-app-x-gate", "scopes": ["kc-admin-api"]}


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
    tls = {"enabled": True, "protocols.web": "https"}

    def lookup(kind, *args, **_kwargs):
        if kind == "sso":
            return get_sso_config(apps, args[0])[args[1]]
        if kind == "config" and args[0] == "web-app-keycloak":
            return KEYCLOAK_CONFIG[args[1]]
        if kind == "config" and args == (APP, OWN_CLIENT_SECRET_PATH):
            return OWN_CLIENT_SECRET
        if kind == "config":
            return "placeholder-cookie"
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


def render(template: str, apps: dict) -> str:
    """Render one oauth2-proxy config template of ``web-app-x``.

    Args:
        template: the template path relative to the repository root.
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
    for filters in (
        CookieScopeFilters,
        NetworkFilters,
        EntityNameFilters,
        ClaimHeaderFilters,
    ):
        env.filters.update(filters().filters())
    return env.get_template(template).render(
        lookup=stub_lookup(apps),
        sso_proxy_application_id=APP,
        sso_proxy_network="clearnet",
        group_names=[],
        DEPLOYMENT_MODE="compose",
        TLS_MODE="letsencrypt",
        DOMAIN_PRIMARY=DOMAIN_PRIMARY,
        RBAC={"GROUP": {"CLAIM": CLAIM}},
        OIDC=OIDC,
    )


def settings(rendered: str) -> dict:
    """
    Args:
        rendered: the rendered config text.

    Returns:
        The ``key = value`` pairs of the rendered oauth2-proxy config.
    """
    pairs = (line.partition("=") for line in rendered.splitlines())
    return {key.strip(): value.strip() for key, sep, value in pairs if sep}


def email_domains(apps: dict) -> str:
    """Return the rendered ``email_domains`` value.

    Args:
        apps: the merged applications payload.
    """
    return settings(render(CONFIG_TEMPLATE, apps))["email_domains"]


def csrf_gaps(config: dict) -> list[str]:
    """
    Args:
        config: the ``key = value`` pairs of a rendered oauth2-proxy config.

    Returns:
        The setting names that let concurrent sign-ins of one browser overwrite
        each other's CSRF cookie; empty when none does.
    """
    gaps = []
    if config.get("cookie_csrf_per_request") != "true":
        gaps.append("cookie_csrf_per_request")
    if (
        not config.get("cookie_csrf_per_request_limit", "").isdigit()
        or int(config["cookie_csrf_per_request_limit"]) < 2
    ):
        gaps.append("cookie_csrf_per_request_limit")
    return gaps


def provider(apps: dict) -> dict:
    """Return the rendered alpha config's only provider.

    Args:
        apps: the merged applications payload.
    """
    return load_yaml_str(render(ALPHA_TEMPLATE, apps))["providers"][0]


class TestAllowedGroups(unittest.TestCase):
    def setUp(self) -> None:
        self.apps = applications(allowed_groups=[GROUP])
        self.provider = provider(self.apps)

    def test_only_the_listed_groups_are_admitted(self) -> None:
        self.assertEqual(self.provider["allowedGroups"], [f"/{GROUP}"])

    def test_the_groups_claim_is_requested(self) -> None:
        self.assertEqual(self.provider["scope"], GROUP_SCOPE)

    def test_the_groups_decide_instead_of_the_email_domain(self) -> None:
        self.assertEqual(email_domains(self.apps), '["*"]')


class TestAllowAllUsers(unittest.TestCase):
    def setUp(self) -> None:
        self.apps = applications(allow_all_users=True)
        self.provider = provider(self.apps)

    def test_no_group_restriction_is_rendered(self) -> None:
        self.assertNotIn("allowedGroups", self.provider)

    def test_the_groups_claim_is_still_forwarded(self) -> None:
        self.assertEqual(
            (self.provider["scope"], self.provider["oidcConfig"]["groupsClaim"]),
            (GROUP_SCOPE, CLAIM),
        )

    def test_external_email_domains_are_admitted(self) -> None:
        self.assertEqual(email_domains(self.apps), '["*"]')

    def test_an_inventory_cleared_group_list_admits_everyone(self) -> None:
        cleared = applications(allowed_groups=[], allow_all_users=True)
        for template in (CONFIG_TEMPLATE, ALPHA_TEMPLATE):
            with self.subTest(template=template):
                self.assertEqual(render(template, cleared), render(template, self.apps))


class TestNeitherKey(unittest.TestCase):
    def setUp(self) -> None:
        self.apps = applications()

    def test_only_the_primary_domain_is_admitted(self) -> None:
        self.assertEqual(email_domains(self.apps), f'"{DOMAIN_PRIMARY}"')

    def test_no_groups_claim_is_requested(self) -> None:
        rendered = provider(self.apps)
        self.assertEqual(
            (rendered["scope"], "allowedGroups" in rendered), (PLAIN_SCOPE, False)
        )

    def test_a_false_allow_all_users_renders_the_same(self) -> None:
        for template in (CONFIG_TEMPLATE, ALPHA_TEMPLATE):
            with self.subTest(template=template):
                self.assertEqual(
                    render(template, applications(allow_all_users=False)),
                    render(template, self.apps),
                )


class TestOwnClient(unittest.TestCase):
    def test_a_declared_client_signs_the_gate_in_with_its_own_credential(self) -> None:
        rendered = provider(applications(client=OWN_CLIENT))
        self.assertEqual(
            (rendered["clientID"], rendered["clientSecret"]),
            (OWN_CLIENT["id"], OWN_CLIENT_SECRET),
        )

    def test_negative_control_without_a_client_the_gate_keeps_the_shared_one(
        self,
    ) -> None:
        rendered = provider(applications())
        self.assertEqual(
            (rendered["clientID"], rendered["clientSecret"]),
            (OIDC["CLIENT"]["ID"], OIDC["CLIENT"]["SECRET"]),
        )

    def test_the_own_client_changes_only_the_credential_lines(self) -> None:
        own = render(ALPHA_TEMPLATE, applications(client=OWN_CLIENT)).splitlines()
        shared = render(ALPHA_TEMPLATE, applications()).splitlines()
        self.assertEqual(
            [pair for pair in zip(own, shared, strict=True) if pair[0] != pair[1]],
            [
                (
                    f'    clientID: "{OWN_CLIENT["id"]}"',
                    f'    clientID: "{OIDC["CLIENT"]["ID"]}"',
                ),
                (
                    f'    clientSecret: "{OWN_CLIENT_SECRET}"',
                    f'    clientSecret: "{OIDC["CLIENT"]["SECRET"]}"',
                ),
            ],
        )

    def test_the_render_of_the_own_client_secret_is_masked(self) -> None:
        tasks = load_yaml_str(
            read_text(str(PROJECT_ROOT / "roles/web-app-keycloak/tasks/sso_proxy.yml"))
        )
        alpha = next(
            task
            for task in tasks
            if "oauth2-proxy-keycloak-alpha.yml.j2"
            in str((task.get("stack_host_template") or {}).get("src"))
        )
        self.assertEqual(alpha["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")


class TestCsrfCookiePerFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.config = settings(render(CONFIG_TEMPLATE, applications()))

    def test_every_sign_in_flow_keeps_its_own_csrf_cookie(self) -> None:
        self.assertEqual(csrf_gaps(self.config), [])

    def test_the_limit_comes_from_the_keycloak_services(self) -> None:
        self.assertEqual(
            self.config["cookie_csrf_per_request_limit"],
            str(KEYCLOAK_CONFIG["services.sso_proxy.csrf_cookie_limit"]),
        )

    def test_negative_control_one_shared_csrf_cookie_is_flagged(self) -> None:
        shared = {
            key: value
            for key, value in self.config.items()
            if not key.startswith("cookie_csrf_per_request")
        }
        self.assertEqual(
            csrf_gaps(shared),
            ["cookie_csrf_per_request", "cookie_csrf_per_request_limit"],
        )

    def test_negative_control_a_limit_of_one_is_flagged(self) -> None:
        self.assertEqual(
            csrf_gaps({**self.config, "cookie_csrf_per_request_limit": "1"}),
            ["cookie_csrf_per_request_limit"],
        )


class TestConflict(unittest.TestCase):
    def test_allow_all_users_with_allowed_groups_fails_the_render(self) -> None:
        apps = applications(allowed_groups=[GROUP], allow_all_users=True)
        for template in (CONFIG_TEMPLATE, ALPHA_TEMPLATE):
            with self.subTest(template=template):
                with self.assertRaises(SsoConfigConflictError) as ctx:
                    render(template, apps)
                for name in (
                    APP,
                    "services.sso.oauth2.allow_all_users",
                    "services.sso.oauth2.allowed_groups",
                ):
                    self.assertIn(name, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
