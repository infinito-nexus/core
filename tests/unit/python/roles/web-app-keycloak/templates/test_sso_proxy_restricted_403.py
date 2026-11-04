from __future__ import annotations

import re
import unittest
import urllib.parse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.roles.applications.services.sso import restricted_locations

from . import PROJECT_ROOT

TEMPLATE = "roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2"
SERVICE_URL = "https://access.example.com/"
GATES = restricted_locations(
    [
        {"location": "/admin", "groups": ["/roles/web-app-shop/administrator"]},
        {
            "location": "/stock",
            "groups": ["roles/web-app-shop/clerk", "/roles/other/x"],
        },
    ]
)
ERROR_PAGE_403 = re.compile(r'(?m)^error_page 403 "([^"]+)";$')


def _render(group_names: tuple[str, ...], auth_uri: str | None) -> str:
    """Render the gate directives of one location of ``web-app-shop``.

    Args:
        group_names: the inventory groups of the host.
        auth_uri: the internal auth URI of a restricted location, None for a plain gate.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )

    def lookup(name: str, *terms, **_kwargs):
        if name == "sso" and terms[1] == "oauth2_restricted_locations":
            return GATES
        if name == "sso" and terms[1] in (
            "oauth2_pass_access_token",
            "oauth2_claim_headers",
        ):
            return []
        if (name, *terms) == ("tls", "web-svc-access-request", "url.base"):
            return SERVICE_URL
        raise AssertionError(f"unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["oauth2_claim_headers"] = lambda attributes, *declared: []
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    context = {
        "application_id": "web-app-shop",
        "group_names": list(group_names),
        "OIDC": {"ATTRIBUTES": {}},
        "RBAC": {"GROUP": {"NAME": "roles"}},
    }
    if auth_uri is not None:
        context["sso_proxy_auth_uri"] = auth_uri
    return env.get_template(TEMPLATE).render(**context)


def _target(rendered: str) -> tuple[str, dict[str, list[str]]]:
    base, _, query = ERROR_PAGE_403.search(rendered).group(1).partition("?")
    return base, urllib.parse.parse_qs(query)


class TestRestrictedLocationRequestPage(unittest.TestCase):
    def test_a_refused_restricted_location_redirects_to_the_request_page(self):
        base, query = _target(
            _render(("web-svc-access-request",), GATES[0]["auth_uri"])
        )

        self.assertEqual(SERVICE_URL, base)
        self.assertEqual(
            {"application": ["web-app-shop"], "role": ["administrator"]}, query
        )

    def test_only_the_application_s_own_groups_become_roles(self):
        _, query = _target(_render(("web-svc-access-request",), GATES[1]["auth_uri"]))

        self.assertEqual(["clerk"], query["role"])

    def test_the_plain_gate_leaves_the_403_to_oauth2_proxy(self):
        self.assertIsNone(
            ERROR_PAGE_403.search(_render(("web-svc-access-request",), None))
        )

    def test_without_the_service_nginx_keeps_its_own_403(self):
        self.assertIsNone(ERROR_PAGE_403.search(_render((), GATES[0]["auth_uri"])))


if __name__ == "__main__":
    unittest.main()
