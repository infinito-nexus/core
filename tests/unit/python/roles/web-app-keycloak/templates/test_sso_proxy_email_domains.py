from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATE = "roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2"
EMAIL_DOMAINS = re.compile(r"(?m)^email_domains\s+=\s+(.+)$")
POLICIES = ("external", "mailbox")


def _email_domains(policy: str, allowed_groups: list[str]) -> str:
    """Render the proxy config and return its ``email_domains`` value.

    Args:
        policy: services.keycloak.email.policy of web-app-keycloak.
        allowed_groups: the app's oauth2_allowed_groups.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    keycloak = {
        "services": {
            "sso_proxy": {"cookie_refresh": "1m"},
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
        if name in ("sso_cookie_domains", "engine"):
            return ""
        if name == "sso_whitelist_domains":
            return []
        raise AssertionError(f"unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["domain_strings"] = lambda domains: domains
    env.filters["in_network"] = lambda domains, _network: domains
    env.filters["to_json"] = str
    rendered = env.get_template(TEMPLATE).render(
        sso_proxy_application_id="web-app-app",
        sso_proxy_network="clearnet",
        DOMAIN_PRIMARY="example.com",
    )
    return EMAIL_DOMAINS.search(rendered).group(1)


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


if __name__ == "__main__":
    unittest.main()
