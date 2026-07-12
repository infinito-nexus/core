"""Lint: role templates MUST resolve app URLs through the central onion-aware lookup.

A deployment can run an app on clearnet (``https://…``) or, when ``svc-net-tor``
is deployed and the app opts in, on a plaintext ``.onion`` (``http://…``). Every
place that builds an app URL by hand — concatenating a protocol with a domain,
or post-processing a URL through the ``to_onion_url`` filter — has to repeat that
clearnet-vs-onion decision and drifts out of sync.

The single source of truth is ``lookup('canonical_url', application_id[, key])``
(and ``lookup('tls', app, 'url.base')`` for the primary): it derives the scheme
from the resolved domain (onion → http, else the TLS setting) using the
onion-injected domain map, so callers never branch themselves.

Forbidden in ``roles/*/templates`` Jinja:
  - manual scheme/host concatenation: ``~ '://'`` / ``'://' ~``
  - the ``to_onion_url`` filter (URL onionization belongs in the lookup)

Exempt: the request-time rewriters that must decide per request, not at render
time — the nginx body filter and the dashboard OIDC loader.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

# Runtime rewriters that legitimately onionize inside generated lua/js.
_EXEMPT_SUFFIXES: tuple[str, ...] = (
    "sys-front-inj-all/templates/body_filter.lua.j2",
    "web-app-dashboard/templates/javascript/oidc.js.j2",
)

_JINJA_COMMENT = re.compile(r"{#.*?#}", re.DOTALL)

# `~ '://'` or `'://' ~` — a URL assembled from a protocol and a host.
_MANUAL_SCHEME = re.compile(r"~\s*['\"]://|://['\"]\s*~")
_TO_ONION = re.compile(r"\bto_onion_url\b")


def _target_files():
    for raw in iter_project_files(extensions=(".j2",), exclude_tests=True):
        path = Path(raw)
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if "/roles/" not in f"/{rel}":
            continue
        if rel.endswith(_EXEMPT_SUFFIXES):
            continue
        yield path


def _strip(text: str) -> str:
    return _JINJA_COMMENT.sub(lambda m: "\n" * m.group().count("\n"), text)


class TestOnionUrlCentralLookup(unittest.TestCase):
    def test_no_manual_url_or_onionize(self):
        offenders: list[str] = []
        for path in _target_files():
            raw = read_text(str(path))
            stripped = _strip(raw)
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for pat, why in (
                (_MANUAL_SCHEME, "manual scheme/host concatenation"),
                (_TO_ONION, "to_onion_url filter"),
            ):
                for m in pat.finditer(stripped):
                    line = stripped[: m.start()].count("\n") + 1
                    offenders.append(f"{rel}:{line}: {why}")
        if offenders:
            self.fail(
                "Build app URLs via lookup('canonical_url', app[, key]) / "
                "lookup('tls', app, 'url.base'), not by hand:\n"
                + "\n".join(f"  - {o}" for o in sorted(offenders))
            )


if __name__ == "__main__":
    unittest.main()
