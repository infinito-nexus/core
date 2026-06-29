"""Makefile target documentation schema.

A target's comment block (the consecutive `# ...` lines directly above it,
no blank line in between) MUST consist of:

  1. Exactly one **description** line at the top of the block (closest to
     the preceding `.PHONY:` line). This is free-text prose explaining
     WHAT the target does. It MUST NOT itself match one of the schema
     markers listed below.
  2. Zero or more **schema** lines below the description, each matching
     exactly one of these markers (case-sensitive):

        # Usage: <invocation>
        # Example: <example>
        # Note: <note>
        # Param <name>: <explanation>

`# nocheck:` suppression markers are ignored — they are not WHY-comments
and do not participate in the schema.
"""

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
_COMMENT_RE = re.compile(r"^\s*#")
_NOCHECK_RE = re.compile(r"^\s*#\s*nocheck\s*:")
_SCHEMA_RE = re.compile(
    r"^\s*#\s*(?:Usage|Example|Note|Param\s+[A-Za-z_][A-Za-z0-9_-]*)\s*:\s+\S"
)


@dataclass(frozen=True)
class _Violation:
    line_no: int
    target: str
    reason: str


def _comment_block_above(lines: list[str], target_idx: int) -> list[tuple[int, str]]:
    """Return the consecutive non-nocheck `#`-lines directly above
    *target_idx*, ordered top-down (description first, schema lines after).
    """
    block: list[tuple[int, str]] = []
    cursor = target_idx - 1
    while cursor >= 0:
        line = lines[cursor]
        if _COMMENT_RE.match(line):
            if not _NOCHECK_RE.match(line):
                block.append((cursor + 1, line))
            cursor -= 1
            continue
        break
    block.reverse()
    return block


def _scan_file(path: Path) -> list[_Violation]:
    lines = read_text(str(path)).splitlines()
    out: list[_Violation] = []
    for index, line in enumerate(lines):
        match = _TARGET_RE.match(line)
        if match is None:
            continue
        block = _comment_block_above(lines, index)
        if not block:
            continue

        description_line_no, description_text = block[0]
        if _SCHEMA_RE.match(description_text):
            out.append(
                _Violation(
                    description_line_no,
                    match.group("name"),
                    "missing description line above the schema block "
                    f"(first comment line matches a schema marker: {description_text.strip()!r})",
                )
            )
            continue

        for schema_line_no, schema_text in block[1:]:
            if not _SCHEMA_RE.match(schema_text):
                out.append(
                    _Violation(
                        schema_line_no,
                        match.group("name"),
                        "schema marker required (one of "
                        "`Usage:`, `Example:`, `Note:`, `Param <name>:`), "
                        f"got: {schema_text.strip()!r}",
                    )
                )
    return out


class TestMakefileCommentSchema(unittest.TestCase):
    def test_makefile_target_comment_blocks_follow_schema(self) -> None:
        path = PROJECT_ROOT / "Makefile"
        self.assertTrue(path.is_file(), "Makefile not found at project root")

        violations = _scan_file(path)
        if not violations:
            return

        lines = [
            f"Makefile targets with comment-block schema violations "
            f"({len(violations)} offences):",
            "",
            "Each target's comment block MUST be: one description line (free text, no marker) followed by zero or more schema lines marked `Usage:`, `Example:`, `Note:`, or `Param <name>:`.",
            "",
            "Offenders:",
        ]
        lines.extend(
            f"  Makefile:{v.line_no} ({v.target}): {v.reason}" for v in violations
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
