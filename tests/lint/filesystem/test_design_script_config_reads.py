"""Lint: a design script reads its config object, it does not quote it.

``sys-front-inj-design`` prepends a line that reads the branding config from
the script tag's ``data-design`` attribute into ``INFINITO_DESIGN``, so the
script reads branding through that object. Writing the reference inside a
string literal produces valid JavaScript that assigns the 34-character text
``INFINITO_DESIGN.urls.favicon_ico`` instead of the URL.

Nothing downstream sees it: the file parses, ``to_one_liner`` collapses it,
eslint accepts a string literal, and the CSP hash matches the broken script.
Only the rendered page shows it, as a favicon that resolves against the page
URL. That is how the documentation role lost its favicon.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLES = PROJECT_ROOT / "roles"
PATTERNS = (
    "*/templates/design.js",
    "*/templates/design.js.j2",
    "*/templates/js/design.js.j2",
)
LITERAL = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|`[^`\n]*`")
INTERPOLATED = re.compile(r"\{\{[^}]*\bdesign\.urls\b")
RULE = "design-script-config-reads"


class TestDesignScriptConfigReads(unittest.TestCase):
    def test_no_script_quotes_its_config_object(self) -> None:
        scripts = [path for pattern in PATTERNS for path in sorted(ROLES.glob(pattern))]
        self.assertTrue(scripts, f"[{RULE}] no design script matched {PATTERNS}")
        offenders = []
        for path in scripts:
            for number, line in enumerate(read_text(str(path)).splitlines(), start=1):
                if any("INFINITO_DESIGN" in text for text in LITERAL.findall(line)):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{number}: {line.strip()[:90]}"
                    )
        self.assertFalse(
            offenders,
            f"[{RULE}] the config object is quoted here, so the script assigns "
            "its own source text instead of the branding value:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_script_bakes_a_branding_url_into_its_body(self) -> None:
        scripts = [path for pattern in PATTERNS for path in sorted(ROLES.glob(pattern))]
        self.assertTrue(scripts, f"[{RULE}] no design script matched {PATTERNS}")
        offenders = []
        for path in scripts:
            for number, line in enumerate(read_text(str(path)).splitlines(), start=1):
                if INTERPOLATED.search(line):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{number}: {line.strip()[:90]}"
                    )
        self.assertFalse(
            offenders,
            f"[{RULE}] these interpolate a branding URL into the script body. "
            "CSP hashes the body, an onion vhost rewrites the CDN host inside "
            "it, and the hash then matches nothing, so the script is refused. "
            "Read the value from INFINITO_DESIGN instead:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
