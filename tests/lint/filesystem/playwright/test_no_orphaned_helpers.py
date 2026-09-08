"""Every role Playwright file is either collected or required.

``playwright.config.js`` collects ``**/*.@(spec|test).js`` and nothing else, so
a ``.js`` file that no sibling requires is dead weight that still reads as part
of the suite. It survives refactors, gets updated by mistake, and a merge can
resurrect one long after the spec that used it was renamed away, which is how
``web-app-openwebui/files/playwright/test-ollama-chat.js`` came back.

A file therefore has to earn its place one of two ways: it matches the collector
by name, or something else under the same role's ``files/playwright/`` requires
it through a relative path. Requires are resolved the way Node resolves them,
including the bare and ``/index.js`` forms.

Suppress a file that is staged for a consumer outside this tree with
``// nocheck: playwright-orphan -- <reason>`` anywhere in it.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_COLLECTED = re.compile(r"\.(?:spec|test)\.js$")
_REQUIRE = re.compile(r"""require\(\s*['"](\.[^'"]+)['"]\s*\)""")
_NOCHECK = re.compile(r"//\s*nocheck:\s*playwright-orphan\b")


def _playwright_files_by_role() -> dict[str, list[Path]]:
    by_role: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(PROJECT_ROOT.glob("roles/*/files/playwright/**/*.js")):
        by_role[path.relative_to(PROJECT_ROOT).parts[1]].append(path)
    return by_role


def _required_targets(files: list[Path]) -> set[Path]:
    """Return every file the given files require through a relative path."""
    reached: set[Path] = set()
    for path in files:
        for ref in _REQUIRE.findall(read_text(str(path))):
            target = (path.parent / ref).resolve()
            for candidate in (target, target.with_suffix(".js"), target / "index.js"):
                if candidate.is_file():
                    reached.add(candidate)
                    break
    return reached


class TestNoOrphanedPlaywrightHelpers(unittest.TestCase):
    def test_every_playwright_file_is_collected_or_required(self) -> None:
        findings: list[str] = []
        for _role, files in sorted(_playwright_files_by_role().items()):
            reached = _required_targets(files)
            for path in files:
                if _COLLECTED.search(path.name) or path.resolve() in reached:
                    continue
                if _NOCHECK.search(read_text(str(path))):
                    continue
                findings.append(str(path.relative_to(PROJECT_ROOT)))

        self.assertFalse(
            findings,
            f"{len(findings)} Playwright file(s) are neither collected by "
            f"playwright.config.js nor required by a sibling under the same "
            f"role. Rename to *.spec.js if it is a test, require it where it "
            f"belongs, delete it, or mark it with "
            f"'// nocheck: playwright-orphan -- <reason>':\n"
            + "\n".join(f"  {name}" for name in findings),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
