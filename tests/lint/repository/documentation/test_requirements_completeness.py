"""Lint requirements completeness under ``docs/requirements/``.

:meth:`TestRequirementsCompleteness.test_requirement_acceptance_criteria_are_complete`
scans each ``NNN-topic.md`` under the ``## Acceptance Criteria``
heading and emits one warning annotation per unchecked ``- [ ]``
item. Warnings only — never fails.

See [requirements.md](../../docs/contributing/requirements.md).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions, warning
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

REQUIREMENTS_DIR = PROJECT_ROOT / "docs" / "requirements"
TEMPLATE_FILENAME = "000-template.md"

REQUIREMENT_FILENAME_RE = re.compile(r"^\d{3}-[^/]+\.md$")
ACCEPTANCE_HEADING_RE = re.compile(r"^##\s+Acceptance Criteria\b", re.IGNORECASE)
SECTION_END_HEADING_RE = re.compile(r"^#{1,2}\s+\S")
UNCHECKED_ITEM_RE = re.compile(r"^\s*[-*+]\s+\[\s\]\s+(?P<body>\S.*)$")
WHITESPACE_RE = re.compile(r"\s+")


def iter_requirement_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file()
        and REQUIREMENT_FILENAME_RE.match(p.name)
        and p.name != TEMPLATE_FILENAME
    )


@dataclass(frozen=True)
class UncheckedCriterion:
    path: Path
    line: int
    text: str

    def relative(self, root: Path) -> str:
        return self.path.relative_to(root).as_posix()

    def message(self) -> str:
        return WHITESPACE_RE.sub(" ", self.text).strip()


def scan_unchecked_criteria(path: Path) -> list[UncheckedCriterion]:
    try:
        lines = read_text(str(path)).splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[UncheckedCriterion] = []
    in_acceptance = False

    for line_no, line in enumerate(lines, start=1):
        if ACCEPTANCE_HEADING_RE.match(line):
            in_acceptance = True
            continue
        if in_acceptance and SECTION_END_HEADING_RE.match(line):
            break
        if not in_acceptance:
            continue

        match = UNCHECKED_ITEM_RE.match(line)
        if not match:
            continue

        findings.append(
            UncheckedCriterion(
                path=path,
                line=line_no,
                text=match.group("body"),
            )
        )

    return findings


def emit_warning(finding: UncheckedCriterion, root: Path) -> None:
    warning(
        finding.message(),
        title="Unchecked acceptance criterion",
        file=finding.relative(root),
        line=finding.line,
    )


def print_summary(findings: list[UncheckedCriterion], root: Path) -> None:
    grouped: dict[str, list[UncheckedCriterion]] = {}
    for item in findings:
        grouped.setdefault(item.relative(root), []).append(item)

    print()
    print(f"[WARNING] Unchecked acceptance criteria ({len(findings)}):")
    for rel_path, items in grouped.items():
        print(f"  {rel_path} ({len(items)}):")
        for item in items:
            print(f"    L{item.line}: {item.message()}")


class TestRequirementsCompleteness(unittest.TestCase):
    def test_requirement_acceptance_criteria_are_complete(self) -> None:
        """Surface every unchecked acceptance criterion as a warning."""
        findings: list[UncheckedCriterion] = []
        for path in iter_requirement_files(REQUIREMENTS_DIR):
            findings.extend(scan_unchecked_criteria(path))

        findings.sort(key=lambda f: (f.path.as_posix(), f.line))

        if not findings:
            print("All acceptance criteria are checked off.")
            return

        for item in findings:
            emit_warning(item, PROJECT_ROOT)

        if not in_github_actions():
            print_summary(findings, PROJECT_ROOT)


if __name__ == "__main__":
    unittest.main()
