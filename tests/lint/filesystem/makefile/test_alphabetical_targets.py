"""Makefile target definitions must be listed in ASC order."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_TARGET_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*:")


@dataclass(frozen=True)
class _Target:
    line_no: int
    name: str


def _targets_in(path: Path) -> list[_Target]:
    out: list[_Target] = []
    for index, line in enumerate(read_text(str(path)).splitlines(), start=1):
        match = _TARGET_RE.match(line)
        if match is None:
            continue
        out.append(_Target(index, match.group("name")))
    return out


class TestMakefileTargetsAlphabetical(unittest.TestCase):
    def test_makefile_targets_sorted_ascending(self) -> None:
        path = PROJECT_ROOT / "Makefile"
        self.assertTrue(path.is_file(), "Makefile not found at project root")

        targets = _targets_in(path)
        self.assertTrue(targets, "no targets found in Makefile")

        names = [t.name for t in targets]
        sorted_names = sorted(names)
        if names == sorted_names:
            return

        violations: list[str] = []
        for target, expected in zip(targets, sorted_names, strict=True):
            if target.name != expected:
                violations.append(
                    f"  Makefile:{target.line_no}: {target.name} (expected {expected})"
                )

        self.fail(
            "Makefile target definitions must appear in ASC order "
            f"({len(violations)} out of place):\n" + "\n".join(violations)
        )


if __name__ == "__main__":
    unittest.main()
