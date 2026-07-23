"""Lint: role templates and CSP whitelists MUST NOT hardcode an external
CDN URL. Browser-facing frontend dependencies belong in the role's
package.json and are resolved through ``lookup('asset', ...)`` /
``lookup('asset_host')``, which serve them from web-svc-cdn (flavor
internal) or fall back to jsdelivr (flavor external) from one pinned,
lockfile-reproducible SPOT. A hardcoded CDN URL is both a supply-chain
hazard (unpinned @latest, no integrity) and a runtime flakiness source
(the browser must resolve an external host).

Suppress a legitimate exception with ``# nocheck: external-cdn`` on the
same line. Pre-existing hardcoded CDNs are checked out with the marker
plus a ``TODO`` so they surface for migration to the asset mechanism.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_CSP

from . import PROJECT_ROOT

_RULE = "external-cdn"

_CDN_HOSTS = (
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "kit.fontawesome.com",
    "ka-f.fontawesome.com",
    "code.jquery.com",
    "ajax.googleapis.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "stackpath.bootstrapcdn.com",
)
_CDN_RE = re.compile(
    r"https://(?:" + "|".join(re.escape(h) for h in _CDN_HOSTS) + r")\b"
)

_GLOBS = (
    "roles/*/templates/**/*.j2",
    "roles/*/templates/**/*.html",
    f"roles/*/{ROLE_FILE_META_CSP}",
)


class TestNoExternalCdn(unittest.TestCase):
    def test_no_hardcoded_external_cdn(self) -> None:
        offenders: list[str] = []
        for glob in _GLOBS:
            for path in sorted(PROJECT_ROOT.glob(glob)):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                lines = read_text(str(path)).splitlines()
                for no, line in enumerate(lines, start=1):
                    if not _CDN_RE.search(line):
                        continue
                    if is_suppressed_at(lines, no, _RULE):
                        continue
                    offenders.append(f"{rel}:{no}: {line.strip()[:100]}")

        if offenders:
            self.fail(
                f"{len(offenders)} hardcoded external CDN URL(s). Declare the "
                "dependency in the role's package.json and use "
                "lookup('asset', ...) / lookup('asset_host'), or mark a "
                f"legitimate exception with `# nocheck: {_RULE}`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
