from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.security_headers import FilterModule
from utils.tls_common import resolve_enabled

from . import PROJECT_ROOT

TEMPLATE = "roles/sys-front-tls/templates/nginx_ssl_header.j2"

PLATFORM = {
    "nosniff": False,
    "referrer_policy": "",
    "permissions_policy": "",
    "hsts": {"max_age": 31536000, "include_subdomains": False, "preload": False},
}

PRIMARY_DOMAINS = {
    "web-app-x": "x.example.org",
    "web-app-onion": "x.abcdefghijklmnop.onion",
    "old.example.org": "old.example.org",
}


def render(application_id: str, override: dict) -> str:
    """Return the TLS server header of one vhost.

    Args:
        application_id: the app the vhost belongs to, or a redirect domain.
        override: the app's ``server.security_headers`` block.
    """
    applications = {
        app: {"server": {"security_headers": override}}
        for app in ("web-app-x", "web-app-onion")
    }

    def lookup(kind, *args, **_kw):
        if kind == "applications":
            return applications
        if kind == "tls":
            term, want = args
            enabled = resolve_enabled(
                applications.get(term, {}), True, primary_domain=PRIMARY_DOMAINS[term]
            )
            return {"enabled": enabled, "ports.web": 443 if enabled else 80}[want]
        if kind == "cert":
            return f"/etc/certs/{args[0]}/{args[1]}"
        raise AssertionError(f"unexpected lookup {kind!r}")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters.update(FilterModule().filters())
    env.filters["bool"] = bool
    return env.get_template(TEMPLATE).render(
        application_id=application_id,
        lookup=lookup,
        WEBSERVER_SECURITY_HEADERS=PLATFORM,
    )


def hsts(rendered: str) -> list[str]:
    """Return every Strict-Transport-Security value the header adds.

    Args:
        rendered: the rendered TLS server header.
    """
    return re.findall(
        r'^add_header Strict-Transport-Security "([^"]*)" always;$',
        rendered,
        re.MULTILINE,
    )


class TestHsts(unittest.TestCase):
    def test_the_platform_value_is_one_year_without_subdomains(self):
        self.assertEqual(hsts(render("web-app-x", {})), ["max-age=31536000"])

    def test_include_subdomains_and_preload_are_opt_in_per_app(self):
        rendered = render(
            "web-app-x", {"hsts": {"include_subdomains": True, "preload": True}}
        )
        self.assertEqual(
            hsts(rendered), ["max-age=31536000; includeSubDomains; preload"]
        )

    def test_a_redirect_vhost_sends_the_platform_value(self):
        self.assertEqual(hsts(render("old.example.org", {})), ["max-age=31536000"])

    def test_an_onion_vhost_sends_no_hsts_even_when_opted_in(self):
        rendered = render("web-app-onion", {"hsts": {"include_subdomains": True}})
        self.assertNotIn("Strict-Transport-Security", rendered)
        self.assertNotIn("ssl", rendered)


if __name__ == "__main__":
    unittest.main()
