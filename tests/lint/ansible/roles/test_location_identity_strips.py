"""Lint: a location that proxies must not forward a client's identity headers.

The platform authenticates several applications by trusted header: oauth2-proxy
verifies the session and nginx passes ``X-Forwarded-User`` and its siblings to
the upstream, which believes them. That only holds while a *client* cannot set
those headers itself, which is what
``headers/identity_request_strips.conf.j2`` is for.

nginx makes this easy to lose. ``proxy_set_header`` is array-inherited: a
location declaring any of its own discards every one from the enclosing block,
and ``proxy_pass_request_headers`` defaults to on, so an unlisted client header
reaches the upstream. A location snippet that proxies therefore has to strip
them itself; there is no server-level net below it.

Only ``html.conf.j2`` did. Websocket, upload and image locations forwarded
whatever the client sent.

An SSO-gated branch overwrites the same headers from ``auth_request_set``, so it
is safe on its own, but it earns no exemption here: a snippet carrying both
branches would keep passing after the strip was deleted from the other one.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: location-identity-strip`` in the head of the snippet, naming why
  the location cannot forge an identity.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import PROJECT_ROOT, read_text

_RULE = "location-identity-strip"

LOCATION_DIR = PROJECT_ROOT / "roles/sys-svc-proxy/templates/location"

STRIP_INCLUDE = "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2"

_PROXIES_RE = re.compile(r"proxy_pass|lookup\(\s*['\"]proxy_pass['\"]")


def snippets() -> list:
    """Return every shared location snippet."""
    return sorted(LOCATION_DIR.glob("*.conf.j2"))


def proxying_snippets() -> list:
    """Return the snippets that hand a request to an upstream."""
    return [p for p in snippets() if _PROXIES_RE.search(read_text(str(p)))]


def unstripped() -> list[str]:
    """Return one finding per proxying snippet that forwards client identity."""
    findings = []
    for path in proxying_snippets():
        content = read_text(str(path))
        if is_suppressed_in_head(content.splitlines(), _RULE):
            continue
        if STRIP_INCLUDE in content:
            continue
        findings.append(
            f"{path.relative_to(PROJECT_ROOT)}: proxies without including "
            f"{STRIP_INCLUDE!r}, so a client-supplied X-Forwarded-User reaches "
            f"the upstream"
        )
    return findings


class TestLocationIdentityStrips(unittest.TestCase):
    def test_no_proxying_location_forwards_client_identity(self) -> None:
        findings = unstripped()
        self.assertEqual(
            [],
            findings,
            f"location snippet(s) forwarding a forgeable identity "
            f"({len(findings)}):\n" + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_finds_proxying_snippets(self) -> None:
        self.assertTrue(proxying_snippets(), "no proxying location snippet was scanned")

    def test_a_non_proxying_snippet_is_not_demanded(self) -> None:
        """A snippet that serves from disk cannot forge an upstream identity."""
        self.assertLessEqual(len(proxying_snippets()), len(snippets()))

    def test_the_strip_snippet_covers_the_oauth2_proxy_headers(self) -> None:
        """The strip is only worth requiring if it names what the bridge trusts."""
        content = read_text(str(PROJECT_ROOT / STRIP_INCLUDE))
        for header in (
            "X-Forwarded-User",
            "X-Forwarded-Email",
            "X-Forwarded-Groups",
            "X-Forwarded-Access-Token",
            "X-Forwarded-Preferred-Username",
        ):
            with self.subTest(header=header):
                self.assertIn(f'proxy_set_header {header} ""', content)


if __name__ == "__main__":
    unittest.main()
