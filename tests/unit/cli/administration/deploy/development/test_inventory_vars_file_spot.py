"""Drift guard for the development inventory vars-file SPOT.

The literal path "inventories/development/default.yml" is exposed in
TWO places that must stay in lockstep:

* `default.env` — `INFINITO_INVENTORY_VARS_FILE` (SPOT-of-record for callers
  that go through `make dotenv` / the bash deploy chain).
* `cli/administration/deploy/development/common.DEV_INVENTORY_VARS_FILE`
  — fallback for direct/test invocations that bypass the bash chain.

If they ever drift, init.py and the shell deploy scripts would point at
different files and CI would silently start producing the wrong inventory.
This test parses the env file and asserts the Python constant matches.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

STATIC_ENV = PROJECT_ROOT / "default.env"


def _parse_env_default(file_text: str) -> str:
    # Match: INFINITO_INVENTORY_VARS_FILE=<DEFAULT>   (optional surrounding quotes)
    pattern = re.compile(
        r'^\s*INFINITO_INVENTORY_VARS_FILE=(?P<value>"[^"]*"|\'[^\']*\'|[^\s#]+)\s*(#.*)?$',
        re.MULTILINE,
    )
    match = pattern.search(file_text)
    if not match:
        raise AssertionError(
            "Could not find INFINITO_INVENTORY_VARS_FILE assignment in "
            f"{STATIC_ENV}; pattern was tightened intentionally so any "
            "rewrite of that line forces a matching update here."
        )
    value = match.group("value")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value


class TestInventoryVarsFileSpotDriftGuard(unittest.TestCase):
    def test_env_default_matches_python_fallback(self):
        env_default = _parse_env_default(read_text(str(STATIC_ENV)))
        self.assertEqual(
            env_default,
            DEV_INVENTORY_VARS_FILE,
            "INFINITO_INVENTORY_VARS_FILE default in default.env drifted from "
            "cli.administration.deploy.development.common.DEV_INVENTORY_VARS_FILE. "
            "Update both literals (or, better, rebase one on the other).",
        )

    def test_no_other_caller_hardcodes_the_literal(self):
        # Whitelist: docs (prose), the SPOT itself, this test, and the
        # Python fallback line. Anywhere else that mentions the literal
        # path is a missed SPOT migration.
        literal = "inventories/development/default.yml"
        allowed_relative = {
            "default.env",
            "cli/administration/deploy/development/common.py",
            Path(__file__).relative_to(PROJECT_ROOT).as_posix(),
            # Documentation and historical/comment references stay as-is:
            "docs/administration/deploy.md",
            "roles/web-app-odoo/tasks/03_oidc.yml",
            # The dev inventory file itself sits at the literal path.
            "inventories/development/default.yml",
            # Lint test names the dev inventory as the SPOT for env injections.
            "tests/lint/filesystem/env/test_no_ansible_env_lookups.py",
        }
        offenders: list[str] = []
        scan_extensions = (".py", ".sh", ".yml", ".yaml", ".j2", ".md")
        for path_str in iter_project_files(extensions=scan_extensions):
            path = Path(path_str)
            try:
                rel = path.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if rel in allowed_relative:
                continue
            if any(rel.startswith(prefix + "/") for prefix in (".mypy_cache",)):
                continue
            if rel.startswith("docs/requirements/"):
                continue
            try:
                text = read_text(path_str)
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
