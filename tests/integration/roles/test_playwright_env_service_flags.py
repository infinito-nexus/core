"""Guard: roles that already emit `<SERVICE>_SERVICE_ENABLED` flags in
their Playwright env template MUST follow the strict "true"/"false"
literal contract from requirement 006.

Every `<SERVICE>_SERVICE_ENABLED=...` line MUST resolve at deploy time
to either the literal "true" or "false" string. No other value is
permitted. This test only checks the template source to catch drift
(e.g. a developer writing `... else '0'` by mistake) — it does not
execute Jinja; the deploy-time rendering is the authoritative check.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

ROLES_DIR = os.path.join(REPO_ROOT, "roles")

SERVICE_FLAG_LINE = re.compile(
    r"^([A-Z][A-Z0-9_]+)_SERVICE_ENABLED\s*=\s*(.*)$",
    re.MULTILINE,
)


def _iter_env_templates():
    for role in sorted(os.listdir(ROLES_DIR)):
        tmpl = os.path.join(ROLES_DIR, role, "templates", "playwright.env.j2")
        if os.path.isfile(tmpl):
            yield role, tmpl


class TestPlaywrightEnvServiceFlags(unittest.TestCase):
    def test_every_flag_renders_strict_true_or_false(self):
        offenders = []
        for role, path in _iter_env_templates():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            for match in SERVICE_FLAG_LINE.finditer(content):
                rhs = match.group(2).strip()
                # The rhs MUST be a Jinja expression that yields "true" or
                # "false" as literal strings. Three acceptable shapes:
                #   1) A `{{ ... }}` ternary that ends with `'true'` and
                #      `'false'` (both quote styles accepted).
                #   2) A `{{ ... | string | lower }}` expression whose
                #      operand is a Python boolean (`True`/`False`
                #      lower-case to "true"/"false").
                #   3) The literal string "true" or "false".
                if rhs in ("true", "false"):
                    continue
                looks_like_ternary = "{{" in rhs and (
                    ("'true'" in rhs and "'false'" in rhs)
                    or ('"true"' in rhs and '"false"' in rhs)
                )
                if looks_like_ternary:
                    continue
                looks_like_string_lower = "{{" in rhs and re.search(
                    r"\|\s*string\s*\|\s*lower\b", rhs
                )
                if looks_like_string_lower:
                    continue
                offenders.append(f"{role}: {match.group(1)}_SERVICE_ENABLED = {rhs}")
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Playwright env service flags MUST resolve to literal "
                '"true" or "false". See requirement 006. Offenders:\n'
                + "\n".join(offenders)
            ),
        )


if __name__ == "__main__":
    unittest.main()
