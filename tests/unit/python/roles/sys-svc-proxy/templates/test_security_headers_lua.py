"""Exception: a location with its own ``add_header`` drops every server-level one,
so these headers live in the Lua header filter of ``content_security_policy.conf.j2``.
"""

from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.security_headers import FilterModule
from utils.cache.files import read_text

from . import PROJECT_ROOT

SNIPPET = "roles/sys-svc-proxy/templates/headers/security_headers.lua.j2"
CSP_TEMPLATE = "roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2"

PLATFORM = {
    "nosniff": False,
    "referrer_policy": "",
    "permissions_policy": "",
    "hsts": {"max_age": 31536000, "include_subdomains": False, "preload": False},
}


def render(override: dict) -> str:
    """Return the Lua snippet for an app declaring *override*.

    Args:
        override: the app's ``server.security_headers`` block.
    """
    applications = {"web-app-x": {"server": {"security_headers": override}}}

    def lookup(kind, *_args, **_kw):
        if kind == "applications":
            return applications
        raise AssertionError(f"unexpected lookup {kind!r}")

    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters.update(FilterModule().filters())
    env.filters["to_json"] = json.dumps
    return env.get_template(SNIPPET).render(
        application_id="web-app-x",
        lookup=lookup,
        WEBSERVER_SECURITY_HEADERS=PLATFORM,
    )


def assignment(rendered: str, header: str) -> str:
    """Return the Lua literal assigned to *header*, or an empty string.

    Args:
        rendered: the rendered snippet.
        header: the response header name.
    """
    match = re.search(
        rf'ngx\.header\["{re.escape(header)}"\] = (".*")$', rendered, re.MULTILINE
    )
    return match.group(1) if match else ""


class TestSecurityHeadersSnippet(unittest.TestCase):
    def test_the_platform_values_send_nothing(self):
        self.assertNotIn("ngx.header", render({}))

    def test_nosniff_is_sent_when_opted_in(self):
        rendered = render({"nosniff": True})
        self.assertEqual(
            json.loads(assignment(rendered, "X-Content-Type-Options")), "nosniff"
        )

    def test_the_referrer_policy_never_replaces_the_upstream_one(self):
        rendered = render({"referrer_policy": "strict-origin-when-cross-origin"})
        self.assertRegex(
            rendered,
            r'if not ngx\.header\["Referrer-Policy"\] then\s+'
            r'ngx\.header\["Referrer-Policy"\] = "strict-origin-when-cross-origin"\s+end',
        )

    def test_the_permissions_policy_is_sent_on_documents_only(self):
        rendered = render({"permissions_policy": "camera=(self)"})
        self.assertRegex(
            rendered,
            r'if is_html then\s+ngx\.header\["Permissions-Policy"\] = "camera=\(self\)"\s+end',
        )

    def test_quoted_origins_stay_one_lua_string(self):
        value = 'camera=(self "https://meet.example.org"), microphone=(self)'
        rendered = render({"permissions_policy": value})
        self.assertEqual(json.loads(assignment(rendered, "Permissions-Policy")), value)

    def test_hsts_is_left_to_the_server_level_header(self):
        rendered = render({"hsts": {"include_subdomains": True}})
        self.assertNotIn("Strict-Transport-Security", rendered)


class TestSnippetPlacement(unittest.TestCase):
    def test_the_snippet_runs_inside_the_csp_header_filter_after_is_html(self):
        text = read_text(str(PROJECT_ROOT / CSP_TEMPLATE))
        block = text.index("header_filter_by_lua_block {")
        is_html = text.index("local is_html")
        include = text.index(f"{{% include '{SNIPPET}' %}}")
        block_end = text.index("\n}\n", block)
        self.assertLess(block, is_html)
        self.assertLess(is_html, include)
        self.assertLess(include, block_end)


if __name__ == "__main__":
    unittest.main()
