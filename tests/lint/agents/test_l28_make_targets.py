"""L28: every make target the agent platform relies on exists in the Makefile
and carries a documentation block, so ``make help`` lists it with a description
and no routine or workflow invokes a target that silently does not exist."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

MAKEFILE = PROJECT_ROOT / "Makefile"
TARGETS = (
    "agents-verify",
    "agents-integration",
    "agents-stop",
    "agents-preseed",
    "ci-wait",
    "test-ref",
    "i18n-pause",
    "i18n-resume",
    "i18n-load",
    "legal-inventory",
    "legal-probe",
)

_COMMENT = re.compile(r"^\s*#")
_NOCHECK = re.compile(r"^\s*#\s*nocheck\s*:")


def _definition_lines(lines: list[str], target: str) -> list[int]:
    """Indices of the recipe lines that define *target* (``<target>:``)."""
    pattern = re.compile(r"^" + re.escape(target) + r"\s*:")
    return [index for index, line in enumerate(lines) if pattern.match(line)]


def _is_documented(lines: list[str], index: int) -> bool:
    """True when a non-nocheck comment block sits directly above *index*."""
    cursor = index - 1
    while cursor >= 0 and _COMMENT.match(lines[cursor]):
        if not _NOCHECK.match(lines[cursor]):
            return True
        cursor -= 1
    return False


def check(makefile: Path, targets: tuple[str, ...] = TARGETS) -> list[str]:
    problems: list[str] = []
    lines = read_text(str(makefile)).splitlines() if makefile.is_file() else []
    for target in targets:
        defined = _definition_lines(lines, target)
        if not defined:
            problems.append(f"make target '{target}' is not defined in the Makefile")
            continue
        if not any(_is_documented(lines, index) for index in defined):
            problems.append(
                f"make target '{target}' has no documentation block above it"
            )
    return problems


class TestL28(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(MAKEFILE), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mk = Path(tmp) / "Makefile"
            mk.write_text("agents-verify:\n\t@echo hi\n", encoding="utf-8")
            self.assertNotEqual(check(mk), [])


if __name__ == "__main__":
    unittest.main()
