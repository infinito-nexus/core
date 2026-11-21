from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATE = "roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2"
EMAIL_DOMAINS = re.compile(r"(?m)^email_domains\s+=\s+(.+)$")
CUSTOM_TEMPLATES_DIR = re.compile(r"(?m)^custom_templates_dir\s+=\s+(.+)$")
POLICIES = ("external", "mailbox")
ACCESS_REQUEST = "web-svc-access-request"


def _render(
    policy: str,
    allowed_groups: list[str],
    any_email: bool = False,
    group_names: tuple[str, ...] = (),
) -> str:
    """Render the proxy config of one gated application.

    Args:
        policy: services.keycloak.email.policy of web-app-keycloak.
        allowed_groups: the app's oauth2_allowed_groups.
        any_email: the app's oauth2_any_email.
        group_names: the inventory groups of the host.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    keycloak = {
        "services": {
            "sso_proxy": {"cookie_refresh": "1m", "templates_directory": "/templates"},
            "keycloak": {"email": {"policy": policy}},
        }
    }

    def lookup(name: str, *terms, **_kwargs):
        if name == "config" and terms[0] == "web-app-keycloak":
            node = keycloak
            for part in terms[1].split("."):
                node = node[part]
            return node
        if name == "config":
            return "cookie-secret"
        if name == "domains":
            return ["app.example.com"]
        if name == "tls":
            return True if terms[1] == "enabled" else "https"
        if name == "sso" and terms[1] == "oauth2_allowed_groups":
            return allowed_groups
        if name == "sso" and terms[1] == "oauth2_any_email":
            return any_email
        if name == "sso" and terms[1] == "oauth2_allow_all_users":
            return False
        if name in ("sso_cookie_domains", "engine"):
            return ""
        if name == "sso_whitelist_domains":
            return []
        raise AssertionError(f"unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["domain_strings"] = lambda domains: domains
    env.filters["in_network"] = lambda domains, _network: domains
    env.filters["to_json"] = str
    return env.get_template(TEMPLATE).render(
        sso_proxy_application_id="web-app-app",
        sso_proxy_network="clearnet",
        DOMAIN_PRIMARY="example.com",
        group_names=list(group_names),
    )


def _email_domains(
    policy: str, allowed_groups: list[str], any_email: bool = False
) -> str:
    """Render the proxy config and return its ``email_domains`` value.

    Args:
        policy: services.keycloak.email.policy of web-app-keycloak.
        allowed_groups: the app's oauth2_allowed_groups.
        any_email: the app's oauth2_any_email.
    """
    return EMAIL_DOMAINS.search(_render(policy, allowed_groups, any_email)).group(1)


class TestSsoProxyEmailDomains(unittest.TestCase):
    def test_an_app_without_allowed_groups_admits_only_the_primary_domain(self):
        for policy in POLICIES:
            with self.subTest(policy=policy):
                self.assertEqual(_email_domains(policy, []), '"example.com"')

    def test_an_app_with_allowed_groups_leaves_the_gate_to_the_groups(self):
        for policy in POLICIES:
            with self.subTest(policy=policy):
                self.assertEqual(
                    _email_domains(policy, ["/roles/web-app-app"]), '["*"]'
                )

    def test_an_app_admitting_any_email_admits_every_domain_without_groups(self):
        for policy in POLICIES:
            with self.subTest(policy=policy):
                self.assertEqual(_email_domains(policy, [], any_email=True), '["*"]')


class TestSsoProxyErrorPage(unittest.TestCase):
    def test_a_group_gated_app_reads_the_custom_403_page_with_the_service(self):
        rendered = _render(
            "external", ["/roles/web-app-app"], group_names=(ACCESS_REQUEST,)
        )

        self.assertEqual(CUSTOM_TEMPLATES_DIR.search(rendered).group(1), '"/templates"')

    def test_without_the_access_request_service_the_default_page_stays(self):
        rendered = _render("external", ["/roles/web-app-app"])

        self.assertIsNone(CUSTOM_TEMPLATES_DIR.search(rendered))

    def test_an_app_without_role_groups_keeps_the_default_page(self):
        rendered = _render(
            "external", [], any_email=True, group_names=(ACCESS_REQUEST,)
        )

        self.assertIsNone(CUSTOM_TEMPLATES_DIR.search(rendered))


if __name__ == "__main__":
    unittest.main()
