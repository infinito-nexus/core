"""Every Makefile target MUST have a `.PHONY: <target>` declaration above its
comment block, and every `.PHONY` entry MUST refer to a defined target."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_TARGET_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*:(?!=)")
_PHONY_RE = re.compile(r"^\.PHONY\s*:\s*(?P<names>.+?)\s*$")
_COMMENT_RE = re.compile(r"^\s*#")


@dataclass(frozen=True)
class _Target:
    line_no: int
    name: str


@dataclass(frozen=True)
class _PhonyDecl:
    line_no: int
    name: str


def _parse_makefile(path: Path) -> tuple[list[_Target], list[_PhonyDecl], list[str]]:
    lines = read_text(str(path)).splitlines()
    targets: list[_Target] = []
    phonys: list[_PhonyDecl] = []
    for idx, line in enumerate(lines, start=1):
        phony_match = _PHONY_RE.match(line)
        if phony_match is not None:
            phonys.extend(
                _PhonyDecl(idx, name) for name in phony_match.group("names").split()
            )
            continue
        target_match = _TARGET_RE.match(line)
        if target_match is None:
            continue
        targets.append(_Target(idx, target_match.group("name")))
    return targets, phonys, lines


def _phony_line_above(
    target: _Target, phonys: list[_PhonyDecl], lines: list[str]
) -> int | None:
    """Return the `.PHONY: <target>` line number that immediately precedes the
    target (across an optional comment block). `None` when missing or when
    something other than a comment lies between the PHONY line and the target."""
    candidates = [
        p for p in phonys if p.name == target.name and p.line_no < target.line_no
    ]
    if not candidates:
        return None
    phony = max(candidates, key=lambda p: p.line_no)
    for between in lines[phony.line_no : target.line_no - 1]:
        if not _COMMENT_RE.match(between):
            return None
    return phony.line_no


class TestMakefilePhonyDeclarations(unittest.TestCase):
    def setUp(self) -> None:
        self.path = PROJECT_ROOT / "Makefile"
        self.assertTrue(self.path.is_file(), "Makefile not found at project root")
        self.targets, self.phonys, self.lines = _parse_makefile(self.path)

    def test_every_target_has_phony_above_comment(self) -> None:
        violations: list[str] = [
            f"  Makefile:{target.line_no}: '{target.name}' has no `.PHONY: {target.name}` "
            "line directly above its comment block"
            for target in self.targets
            if _phony_line_above(target, self.phonys, self.lines) is None
        ]
        if violations:
            self.fail(
                f"{len(violations)} target(s) missing a `.PHONY` declaration "
                "above the comment:\n" + "\n".join(violations)
            )

    def test_no_orphan_phony(self) -> None:
        target_names = {t.name for t in self.targets}
        orphans = [p for p in self.phonys if p.name not in target_names]
        if orphans:
            self.fail(
                f"{len(orphans)} `.PHONY` entry/entries reference targets that do not exist:\n"
                + "\n".join(f"  Makefile:{p.line_no}: '{p.name}'" for p in orphans)
            )


if __name__ == "__main__":
    unittest.main()
