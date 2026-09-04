"""Lint: a Playwright helper a spec imports must be staged next to it.

Two stagers copy role specs into `/e2e/tests/` and, beside them, the shared
helpers: the deploy task and `rerun-spec.sh`. Both used to name the helpers,
and had already drifted apart. A spec importing a helper neither stager copies
fails at import with `Cannot find module`, for every role that imports it at
once.

The scan set is what the specs actually import, not a list of helper names: a
require that resolves to a sibling in the role's own playwright directory is
role-local and needs no staging, and everything else must be staged.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: playwright-helper-staged`` on, or directly above, the require.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import (
    PROJECT_ROOT,
    iter_project_files_with_content,
    read_text,
)

_RULE = "playwright-helper-staged"

RUNNER_FILES = PROJECT_ROOT / "roles/test-e2e-playwright/files"
STAGING_TASK = PROJECT_ROOT / "roles/test-e2e-playwright/tasks/02_run_one.yml"
RERUN_SCRIPT = PROJECT_ROOT / "scripts/tests/e2e/rerun-spec.sh"
LINT_SCRIPT = PROJECT_ROOT / "scripts/lint/playwright.sh"

_REQUIRE_RE = re.compile(r"""require\(["']\./([A-Za-z0-9._-]+)["']\)""")

_MOUNTED_AS_DIRECTORY = frozenset({"personas"})

_NOT_A_HELPER = frozenset({"playwright.config.js"})

_GLOB_MARKER = "roles/test-e2e-playwright/files') }}/*.js"
_SHELL_GLOB_MARKER = 'roles/test-e2e-playwright/files"/*.js'
_LINT_GLOB_MARKER = '"${HELPERS_SRC}"/*.js'


def staged_helpers() -> set[str]:
    """Return the helper file names both stagers copy into the tests dir.

    Neither stager names them any more: the deploy task globs the runner's own
    `files/*.js` and `rerun-spec.sh` does the same, so the directory listing is
    the set. Three hand-maintained copies of it had already drifted apart when
    that was the design.
    """
    return {
        path.name
        for path in RUNNER_FILES.glob("*.js")
        if path.name not in _NOT_A_HELPER
    }


def spec_files() -> list[tuple[str, str]]:
    """Return ``(path, content)`` for every role-local Playwright spec."""
    return [
        (path, content)
        for path, content in iter_project_files_with_content(extensions=(".js",))
        if "/files/playwright/" in path.replace("\\", "/")
    ]


def unstaged_requires() -> list[str]:
    """Return one finding per imported helper the runner never stages."""
    staged = staged_helpers()
    findings = []
    for path, content in spec_files():
        role_dir = Path(path).parent
        lines = content.splitlines()
        for index, line in enumerate(lines, start=1):
            for name in _REQUIRE_RE.findall(line):
                if (role_dir / f"{name}.js").is_file():
                    continue
                if name in _MOUNTED_AS_DIRECTORY:
                    continue
                if is_suppressed_at(lines, index, _RULE):
                    continue
                if f"{name}.js" not in staged:
                    findings.append(
                        f"{path}:{index}: requires {name!r}, which is neither a "
                        f"sibling spec nor staged by 02_run_one.yml"
                    )
    return findings


def stagers_without_the_glob() -> list[str]:
    """Return one finding per stager that stopped deriving the helper set.

    Every stager must glob the runner's `files/*.js`. One that goes back to
    naming helpers drifts from the others silently, which is how three copies
    of the same set came to hold three different sets: the deploy task named
    four, `rerun-spec.sh` three, and `playwright.sh` four again but a
    different four.
    """
    findings = []
    for path, marker in (
        (STAGING_TASK, _GLOB_MARKER),
        (RERUN_SCRIPT, _SHELL_GLOB_MARKER),
        (LINT_SCRIPT, _LINT_GLOB_MARKER),
    ):
        if marker not in read_text(str(path)):
            findings.append(f"{path.name} no longer globs the helper directory")
    return findings


class TestPlaywrightHelpersStaged(unittest.TestCase):
    def test_every_imported_helper_is_staged(self) -> None:
        findings = unstaged_requires()
        self.assertEqual(
            [],
            findings,
            f"Playwright helper import(s) that would fail at runtime "
            f"({len(findings)}):\n" + "\n".join(f"  - {f}" for f in findings),
        )

    def test_both_stagers_derive_the_helper_set(self) -> None:
        findings = stagers_without_the_glob()
        self.assertEqual([], findings, "\n".join(findings))

    def test_the_scan_reaches_the_specs(self) -> None:
        self.assertTrue(
            spec_files(), "no Playwright spec was scanned, so the rule is vacuous"
        )

    def test_the_helper_set_is_not_empty(self) -> None:
        """An empty set would make every shared import look unstaged."""
        self.assertIn("service-gating.js", staged_helpers())

    def test_the_config_is_not_treated_as_a_helper(self) -> None:
        """It is staged one level up, as the run's config, not beside the specs."""
        self.assertNotIn("playwright.config.js", staged_helpers())

    def test_a_shared_helper_is_actually_reached(self) -> None:
        """Role-local siblings dominate the requires; without a shared one in
        the set the rule would pass while never testing what it exists for."""
        shared = {
            name
            for path, content in spec_files()
            for name in _REQUIRE_RE.findall(content)
            if not (Path(path).parent / f"{name}.js").is_file()
            and name not in _MOUNTED_AS_DIRECTORY
        }
        self.assertTrue(shared, "no spec imports a shared helper")


if __name__ == "__main__":
    unittest.main()
