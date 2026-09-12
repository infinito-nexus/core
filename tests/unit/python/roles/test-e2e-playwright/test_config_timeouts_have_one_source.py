"""One source owns every Playwright timeout, and the config keeps no copy.

The config and the role each held a literal for the same value. They drifted
without a sound: ``actionTimeout`` carried ``|| 30_000`` while nothing ever set
the variable, so every run used the unscaled 30 s, and ``expect`` had no entry
at all, leaving Playwright's built-in 5 s to govern every assertion over Tor
while its neighbours were scaled. The second login attempt in
``web-app-nextcloud`` died on ``expect(usernameField).toBeVisible()`` after 5 s
with 150 s around it.

``vars/main.yml`` now owns the values, the harness renders them into the staged
``.env`` that both the deploy and ``scripts/tests/e2e/rerun-spec.sh`` pass, and
the config demands them rather than inventing one.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_ROLE = PROJECT_ROOT / "roles/test-e2e-playwright"
_CONFIG = _ROLE / "files/playwright.config.js"
_VARS = _ROLE / ROLE_FILE_VARS_MAIN
_LINT = PROJECT_ROOT / "scripts/lint/playwright.sh"
_SPOT = "TEST_E2E_PLAYWRIGHT_CONFIG_TIMEOUTS"

_REQUIRED = re.compile(r'requiredTimeout\("(PLAYWRIGHT_\w+)"\)')
_ANY_READ = re.compile(r"process\.env\.(PLAYWRIGHT_\w*TIMEOUT\w*)")


class TestConfigTimeoutsHaveOneSource(unittest.TestCase):
    def test_the_config_demands_exactly_what_the_role_renders(self) -> None:
        demanded = set(_REQUIRED.findall(read_text(str(_CONFIG))))
        self.assertTrue(
            demanded,
            "no requiredTimeout call found in playwright.config.js; the regex "
            "no longer matches how the config takes its timeouts, so this test "
            "has stopped guarding anything",
        )
        rendered = set(load_yaml_any(str(_VARS))[_SPOT])
        self.assertEqual(
            demanded,
            rendered,
            f"the config and {_SPOT} must name the same timeouts: a demanded "
            "one nobody renders aborts every run, and a rendered one nobody "
            "demands is dead weight that reads as configuration",
        )

    def test_the_lint_stager_reads_the_same_map(self) -> None:
        self.assertIn(
            _SPOT,
            read_text(str(_LINT)),
            f"{_LINT.name} stages the config and runs 'playwright test --list', "
            "which loads it and therefore hits the same demand. It has to take "
            f"the names from {_SPOT}, or a rename leaves every role red with a "
            "missing-variable abort that has nothing to do with its spec",
        )

    def test_the_config_keeps_no_timeout_of_its_own(self) -> None:
        stray = set(_ANY_READ.findall(read_text(str(_CONFIG))))
        self.assertEqual(
            set(),
            stray,
            "these timeouts are read straight from the environment, so a "
            "literal beside them becomes a second source the role cannot see: "
            + ", ".join(sorted(stray)),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
