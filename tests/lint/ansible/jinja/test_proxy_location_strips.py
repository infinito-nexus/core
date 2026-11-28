"""Lint: every proxying location the front proxy includes strips upstream headers.

``proxy_hide_header`` is replaced, not merged, by a location that sets its own,
so ``upstream_strips.conf.j2`` only takes effect where a location includes it.
A location fragment without it leaks ``X-Powered-By`` and the upstream's
``Strict-Transport-Security`` on that path alone.

Scope: role templates under ``roles/*/templates/`` and static nginx fragments
under ``roles/*/files/`` that the front proxy renders into a vhost. That is
every such file without a ``server`` block, plus every openresty vhost with its
own ``server`` block, recognised by the TLS server header it includes. Any other
``server`` block is the config of an app-internal nginx behind such a location.

A location counts wherever its matcher is a Jinja expression or its opening
brace sits on the next line, and an ``internal`` one reached as a subrequest
(``ngx.location.capture``) counts like any other: nginx hands it the client's
request headers.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_STRIPS = "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2"
_IDENTITY_STRIPS = (
    "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2",
    "roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2",
)
_FRONT_PROXY_VHOST = "roles/sys-front-tls/templates/nginx_ssl_header.j2"
_SERVER_BLOCK = re.compile(r"^\s*server\s*\{", re.MULTILINE)
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}")
_LOCATION_OPEN = re.compile(r"^\s*location\b[^{]*\{\s*$")
_LOCATION_HEAD = re.compile(r"^\s*location\b[^{;]*$")
_BRACE_LINE = re.compile(r"^\s*\{\s*$")
_PROXYING = re.compile(r"\bproxy_pass\b|lookup\('proxy_pass'|_backend\s*\}\}")


def _role_templates() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".j2", ".conf"), exclude_tests=True)
        if "/roles/" in path
        and (
            ("/templates/" in path and path.endswith(".j2"))
            or ("/files/" in path and path.endswith(".conf"))
        )
    )


def _renders_into_front_proxy(text: str) -> bool:
    return not _SERVER_BLOCK.search(text) or _FRONT_PROXY_VHOST in text


def _masked(line: str) -> str:
    return _JINJA.sub("_", line)


def _location_blocks(lines: list[str]) -> list[tuple[int, str]]:
    """Args:
        lines: the raw template lines.

    Returns:
        ``(line number, raw body)`` per location block. Braces are counted on
        lines whose Jinja delimiters are masked, the body keeps them so an
        ``include`` stays visible.
    """
    masked = [_masked(line) for line in lines]
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if _LOCATION_OPEN.match(masked[index]):
            start, index = index, index + 1
        elif (
            _LOCATION_HEAD.match(masked[index])
            and index + 1 < len(lines)
            and _BRACE_LINE.match(masked[index + 1])
        ):
            start, index = index, index + 2
        else:
            index += 1
            continue
        depth = 1
        body: list[str] = []
        while index < len(lines) and depth > 0:
            depth += masked[index].count("{") - masked[index].count("}")
            body.append(lines[index])
            index += 1
        blocks.append((start + 1, "\n".join(body)))
    return blocks


def _proxying_locations() -> list[tuple[str, int, str]]:
    """Returns ``(relative path, line number, raw body)`` per proxying location
    the front proxy renders."""
    found: list[tuple[str, int, str]] = []
    for path in _role_templates():
        text = read_text(path)
        if not _renders_into_front_proxy(text):
            continue
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        for line, body in _location_blocks(text.splitlines()):
            if _PROXYING.search(body):
                found.append((rel, line, body))
    return found


class TestProxyLocationStrips(unittest.TestCase):
    def test_at_least_one_fragment_is_checked(self) -> None:  # nocheck: test.text-presence -- vacuity guard on the location scan  # fmt: skip
        """Otherwise the assertion below passes over an empty list."""
        self.assertTrue(
            _proxying_locations(), "no proxying location fragment found to check"
        )

    def test_the_parser_reaches_every_location_shape(self) -> None:
        """The shared snippets open with a Jinja matcher or a brace on the next
        line; a parser that skips either shape passes over them silently."""
        lines = [
            "location ^~ {{ path }}/ {",
            "  proxy_pass http://a;",
            "}",
            "location {{ location }}",
            "{",
            "  {{ lookup('proxy_pass', application_id) }}",
            "}",
            "location = /_live_probe {",
            "  internal;",
            "  {{ prometheus_backend }}",
            "}",
        ]
        self.assertEqual([1, 4, 8], [line for line, _ in _location_blocks(lines)])

    def test_openresty_vhosts_with_a_server_block_are_scanned(self) -> None:  # nocheck: test.text-presence -- reach guard of the lint's location scanner  # fmt: skip
        scanned = {rel for rel, _, _ in _proxying_locations()}
        self.assertIn("roles/sys-svc-proxy/templates/location/html.conf.j2", scanned)
        self.assertTrue(
            _renders_into_front_proxy(
                read_text(
                    str(PROJECT_ROOT / "roles/web-app-n8n/templates/proxy.conf.j2")
                )
            )
        )

    def test_proxying_locations_include_the_strips(self) -> None:  # nocheck: test.text-presence -- policy lint over every proxying location block  # fmt: skip
        findings = [
            f"- {rel}:{line}"
            for rel, line, body in _proxying_locations()
            if _STRIPS not in body
        ]
        if findings:
            self.fail(
                "These proxying locations do not include the upstream header strips, "
                "so X-Powered-By and the upstream HSTS leak on their path:\n"
                + "\n".join(findings)
                + f"\n\nFix: add `{{% include '{_STRIPS}' %}}` inside each location."
            )

    def test_proxying_locations_clear_client_identity(self) -> None:  # nocheck: test.text-presence -- policy lint over every proxying location block  # fmt: skip
        """A health, API or exception path of a header-trust vhost reaches the
        same backend as ``/``, so a forged ``X-Forwarded-User`` sent there
        impersonates any user unless the location clears it."""
        findings = [
            f"- {rel}:{line}"
            for rel, line, body in _proxying_locations()
            if not any(strip in body for strip in _IDENTITY_STRIPS)
        ]
        if findings:
            self.fail(
                "These proxying locations forward a client-supplied identity "
                "header (X-Forwarded-User, Remote-User, X-Auth-Request-*) to "
                "their upstream:\n"
                + "\n".join(findings)
                + f"\n\nFix: add `{{% include '{_IDENTITY_STRIPS[0]}' %}}` inside "
                "each location, or the SSO directives on a gated one."
            )


if __name__ == "__main__":
    unittest.main()
