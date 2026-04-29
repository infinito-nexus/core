"""Drift guard for the development inventory vars-file SPOT.

The literal path "inventories/development/default.yml" is exposed in
TWO places that must stay in lockstep:

* `scripts/meta/env/inventory.sh` — `INVENTORY_VARS_FILE` (SPOT-of-record
  for callers that go through the deploy chain; bash sources env first).
* `cli/deploy/development/common.DEV_INVENTORY_VARS_FILE` — fallback for
  direct/test invocations that bypass the bash chain.

If they ever drift, init.py and the shell deploy scripts would point at
different files and CI would silently start producing the wrong inventory.
This test parses the bash file and asserts the Python constant matches.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cli.deploy.development.common import DEV_INVENTORY_VARS_FILE

REPO_ROOT = Path(__file__).resolve().parents[5]
INVENTORY_ENV_SH = REPO_ROOT / "scripts" / "meta" / "env" / "inventory.sh"


def _parse_bash_default(file_text: str) -> str:
    # Match: INVENTORY_VARS_FILE="${INVENTORY_VARS_FILE:-<DEFAULT>}"
    pattern = re.compile(
        r'^\s*INVENTORY_VARS_FILE="\$\{INVENTORY_VARS_FILE:-(?P<value>[^}]+)\}"\s*$',
        re.MULTILINE,
    )
    match = pattern.search(file_text)
    if not match:
        raise AssertionError(
            "Could not find INVENTORY_VARS_FILE default assignment in "
            f"{INVENTORY_ENV_SH}; pattern was tightened intentionally so "
            "any rewrite of that line forces a matching update here."
        )
    return match.group("value")


class TestInventoryVarsFileSpotDriftGuard(unittest.TestCase):
    def test_bash_default_matches_python_fallback(self):
        bash_default = _parse_bash_default(INVENTORY_ENV_SH.read_text(encoding="utf-8"))
        self.assertEqual(
            bash_default,
            DEV_INVENTORY_VARS_FILE,
            "INVENTORY_VARS_FILE default in scripts/meta/env/inventory.sh "
            "drifted from cli.deploy.development.common.DEV_INVENTORY_VARS_FILE. "
            "Update both literals (or, better, rebase one on the other).",
        )

    def test_no_other_caller_hardcodes_the_literal(self):
        # Whitelist: docs (prose), the SPOT itself, this test, and the
        # Python fallback line. Anywhere else that mentions the literal
        # path is a missed SPOT migration.
        literal = "inventories/development/default.yml"
        allowed_relative = {
            "scripts/meta/env/inventory.sh",
            "cli/deploy/development/common.py",
            Path(__file__).relative_to(REPO_ROOT).as_posix(),
            # Documentation and historical/comment references stay as-is:
            "docs/administration/deploy.md",
            "docs/requirements/003-reduce-applications-and-users-to-lookup.md",
            "roles/web-app-odoo/tasks/03_oidc.yml",
            # The dev inventory file itself sits at the literal path.
            "inventories/development/default.yml",
        }
        offenders: list[str] = []
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in allowed_relative:
                continue
            # Skip vendored/build/cache directories.
            if any(
                rel.startswith(prefix + "/")
                for prefix in (
                    ".git",
                    ".venv",
                    "node_modules",
                    "__pycache__",
                    ".pytest_cache",
                    ".mypy_cache",
                )
            ):
                continue
            if path.suffix not in {".py", ".sh", ".yml", ".yaml", ".j2", ".md"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if literal in text:
                offenders.append(rel)
        self.assertFalse(
            offenders,
            "The development inventory vars-file path is hardcoded in "
            "files outside the SPOT whitelist; either route them through "
            "the SPOT or extend the whitelist with a justification: "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
