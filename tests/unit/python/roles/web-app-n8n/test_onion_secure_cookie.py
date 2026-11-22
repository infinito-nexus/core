from __future__ import annotations

import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FunctionLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.files import PROJECT_ROOT, read_text

ENV = PROJECT_ROOT / "roles/web-app-n8n/templates/env.j2"
PROXY = "roles/web-app-n8n/templates/proxy.conf.j2"
SSL_HEADER = "roles/sys-front-tls/templates/nginx_ssl_header.j2"
EDGE_SECURE = "proxy_cookie_flags ~ secure;"
INCLUDE = re.compile(r"\{%-?\s*include\s+['\"]([^'\"]+)['\"]")

CLEAR = "n8n.example.test"
ONION = "n8n." + "a" * 56 + ".onion"


def secure_cookie(web_protocol: str) -> bool:
    """Return what ``env.j2`` sets ``N8N_SECURE_COOKIE`` to.

    Args:
        web_protocol: the role's ``N8N_WEB_PROTOCOL``.
    """
    line = next(
        raw
        for raw in read_text(str(ENV)).splitlines()
        if raw.startswith("N8N_SECURE_COOKIE=")
    )
    rendered = (
        Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        .from_string(line)
        .render(N8N_WEB_PROTOCOL=web_protocol)
    )
    return rendered.partition("=")[2] == "true"


def editor_blocked(secure: bool, scheme: str, host: str) -> bool:
    """Return whether n8n's editor replaces itself with the insecure page.

    Args:
        secure: ``authCookie.secure`` of the public settings.
        scheme: the scheme the browser opened the editor over.
        host: the host the browser opened the editor on.
    """
    return secure and scheme == "http" and host not in ("localhost", "127.0.0.1")


def vhost(domain: str) -> list[str]:
    """Return the stripped lines n8n's own vhost template renders for a domain.

    Args:
        domain: the vhost being rendered; only ``CLEAR`` is served over TLS.
    """

    def lookup(kind, *args):
        if kind == "sso":
            return False
        if kind == "tls" and args == (domain, "enabled"):
            return domain == CLEAR
        raise AssertionError(f"unexpected lookup {kind!r} {args!r}")

    env = Environment(
        loader=ChoiceLoader(
            [
                DictLoader({PROXY: read_text(str(PROJECT_ROOT / PROXY))}),
                FunctionLoader(lambda _name: ""),
            ]
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = bool
    env.filters["network_of"] = lambda d: "tor" if d.endswith(".onion") else "web"
    rendered = env.get_template(PROXY).render(
        application_id="web-app-n8n", domain=domain, lookup=lookup
    )
    return [line.strip() for line in rendered.splitlines()]


def include_closure(name: str) -> set[str]:
    """Return a template and every template it includes by a literal name.

    Args:
        name: the repository-relative path of the template.
    """
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current in seen or not (PROJECT_ROOT / current).is_file():
            continue
        seen.add(current)
        pending.extend(INCLUDE.findall(read_text(str(PROJECT_ROOT / current))))
    return seen


class TestOnionSibling(unittest.TestCase):
    def test_the_editor_opens_on_the_onion_sibling_of_a_tls_node(self) -> None:
        self.assertFalse(editor_blocked(secure_cookie("https"), "http", ONION))

    def test_the_editor_opens_on_a_plain_http_node(self) -> None:
        self.assertFalse(editor_blocked(secure_cookie("http"), "http", ONION))

    def test_the_onion_vhost_adds_no_secure_flag(self) -> None:
        self.assertNotIn(EDGE_SECURE, vhost(ONION))


class TestClearnetVhost(unittest.TestCase):
    def test_a_tls_vhost_marks_every_cookie_secure(self) -> None:
        self.assertEqual(vhost(CLEAR).count(EDGE_SECURE), 1)

    def test_the_clearnet_session_cookie_stays_secure(self) -> None:
        self.assertTrue(secure_cookie("https") or EDGE_SECURE in vhost(CLEAR))

    def test_no_included_location_replaces_the_server_rule(self) -> None:
        included = include_closure(PROXY) - {PROXY, SSL_HEADER}
        self.assertIn("roles/sys-svc-proxy/templates/location/html.conf.j2", included)
        self.assertEqual(
            [
                name
                for name in sorted(included)
                if "proxy_cookie_flags" in read_text(str(PROJECT_ROOT / name))
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()
