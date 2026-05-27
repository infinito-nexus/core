"""Lint guard: deprecated HTTP security headers MUST NOT be re-introduced
into any nginx (``add_header``) or apache (``Header set/add``) config.

Browser vendors have either removed the implementation or marked the
header obsolete; the modern replacement is Content-Security-Policy.
For roles in this repo the canonical CSP SPOT is
``roles/<role>/meta/server.yml`` (`csp.flags` / `csp.whitelist`),
rendered by ``sys-svc-proxy`` via the ``build_csp_header`` filter — that
proxy layer already strips upstream ``Content-Security-Policy`` so the
SPOT wins.

Flagged headers:

* ``X-Frame-Options`` — superseded by CSP ``frame-ancestors``.
* ``X-XSS-Protection`` — removed from modern browsers; can re-introduce
  XSS vectors.
* ``X-Download-Options`` — IE-only directive; IE is EOL.
* ``X-Permitted-Cross-Domain-Policies`` — Adobe Flash / Acrobat era;
  largely irrelevant after Flash EOL.

Fails the suite on any unmarked occurrence. Suppression via
``# nocheck: deprecated-http-header`` on the offending line or on the
immediately preceding non-empty line. File walking and reading go
through the process-wide cache in :mod:`utils.cache.files`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_SCAN_EXTENSIONS = (
    ".conf",
    ".conf.j2",
    ".htaccess",
    ".htaccess.j2",
    ".j2",
    ".jinja",
    ".jinja2",
    ".tmpl",
)

_RULE = "deprecated-http-header"

_DEPRECATED_HEADERS: tuple[str, ...] = (
    "X-Frame-Options",
    "X-XSS-Protection",
    "X-Download-Options",
    "X-Permitted-Cross-Domain-Policies",
)

_NAMES_GROUP = "|".join(re.escape(h) for h in _DEPRECATED_HEADERS)

# Matches both nginx (`add_header NAME`) and apache
# (`Header set NAME`, `Header add NAME`, `Header always set NAME`).
_HEADER_RE = re.compile(
    r"\b(?:add_header|Header\s+(?:always\s+)?(?:set|add))\s+"
    rf"(?P<name>{_NAMES_GROUP})\b",
    re.IGNORECASE,
)

_MIGRATION_HINT = (
    "Use Content-Security-Policy in the role's meta/server.yml "
    "(csp.flags / csp.whitelist). sys-svc-proxy strips upstream CSP "
    "and renders the SPOT via build_csp_header. "
    "Suppress with '# nocheck: deprecated-http-header' if intentional."
)


class TestNoDeprecatedHttpSecurityHeaders(unittest.TestCase):
    def test_no_deprecated_security_headers(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(extensions=_SCAN_EXTENSIONS):
            try:
                text = read_text(path_str)
            except (OSError, UnicodeDecodeError):
                continue
            if "add_header" not in text and "Header" not in text:
                continue

            lines = text.splitlines()
            path = Path(path_str)
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(lines, start=1):
                match = _HEADER_RE.search(line)
                if not match:
                    continue
                if is_suppressed_at(lines, idx, _RULE):
                    continue
                offenders.append(f"{rel}:{idx}: {match.group('name')}: {line.strip()}")

        if offenders:
            self.fail(
                "Deprecated HTTP security headers detected. "
                + _MIGRATION_HINT
                + "\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
