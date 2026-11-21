"""Lint: a superseded line points at the requirement that supersedes it.

A row of a requirement's ``## Superseded ...`` table whose first cell cites
``[NNN](NNN-topic.md) line <n>`` names one line of an earlier requirement
that no longer holds. A reader of the earlier file sees nothing of that, so
the cited line itself MUST link to the superseding requirement file.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable

REQUIREMENTS = PROJECT_ROOT / "docs" / "requirements"
_NAME = re.compile(r"^\d{3}-[^/]+\.md$")
_SECTION = re.compile(r"^##\s+Superseded\b")
_HEADING = re.compile(r"^#{1,2}\s+\S")
_CITATION = re.compile(
    r"^\|\s*\[\d{3}\]\((?P<file>\d{3}-[^)#\s]+\.md)\)\s+line\s+(?P<line>\d+)\s*\|"
)


def citations(text: str) -> list[tuple[str, int]]:
    """Args:
        text: a requirement file.

    Returns:
        The earlier file and line every row of its superseded table cites.
    """
    found: list[tuple[str, int]] = []
    inside = False
    for line in text.splitlines():
        if _SECTION.match(line):
            inside = True
            continue
        if inside and _HEADING.match(line):
            break
        match = _CITATION.match(line) if inside else None
        if match:
            found.append((match["file"], int(match["line"])))
    return found


def missing_pointers(
    name: str, text: str, read: Callable[[str], str | None]
) -> list[str]:
    """Args:
        name: the file name of the superseding requirement.
        text: its content.
        read: returns the content of an earlier requirement by file name, None when absent.

    Returns:
        One finding per cited line that does not link to ``name``.
    """
    findings: list[str] = []
    for cited, number in sorted(set(citations(text))):
        earlier = read(cited)
        lines = earlier.splitlines() if earlier is not None else []
        if not 1 <= number <= len(lines):
            findings.append(f"{name} cites {cited} line {number}, which does not exist")
        elif f"]({name}" not in lines[number - 1]:
            findings.append(f"{cited}:{number} carries no link to {name}")
    return findings


def _read(name: str) -> str | None:
    path = REQUIREMENTS / name
    return read_text(str(path)) if path.is_file() else None


class TestSupersededPointers(unittest.TestCase):
    def test_every_superseded_line_points_at_its_successor(self) -> None:
        findings = [
            finding
            for path in sorted(REQUIREMENTS.iterdir())
            if _NAME.match(path.name)
            for finding in missing_pointers(path.name, read_text(str(path)), _read)
        ]
        self.assertEqual(findings, [], "\n".join(findings))

    def test_a_cited_line_without_the_link_is_reported(self) -> None:
        newer = (
            "## Superseded Statements\n\n| Earlier | Superseded | By |\n|---|---|---|\n"
            "| [001](001-old.md) line 2 | x | y |\n| [001](001-old.md) line 9 | x | y |\n"
        )
        earlier = {"001-old.md": "# 001\n- a statement\n"}
        self.assertEqual(
            missing_pointers("002-new.md", newer, earlier.get),
            [
                "001-old.md:2 carries no link to 002-new.md",
                "002-new.md cites 001-old.md line 9, which does not exist",
            ],
        )
        earlier["001-old.md"] = "# 001\n- a statement, see [002](002-new.md).\n"
        self.assertEqual(
            missing_pointers(
                "002-new.md", newer.replace("line 9", "line 2"), earlier.get
            ),
            [],
        )

    def test_rows_outside_the_superseded_section_are_ignored(self) -> None:
        text = "## Context\n\n| [001](001-old.md) line 2 | x |\n\n## Superseded\n\n## Next\n"
        self.assertEqual(citations(text), [])


if __name__ == "__main__":
    unittest.main()
