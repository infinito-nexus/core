"""Env files (`*.env`, `*.env.j2`): at most one `# ...` comment line directly above each entry."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
_COMMENT_RE = re.compile(r"^\s*#")
# nocheck:foo / nocheck: foo markers are suppression directives, not WHY comments.
_NOCHECK_RE = re.compile(r"^\s*#\s*nocheck\s*:")


@dataclass(frozen=True)
class _Violation:
    file: str
    line_no: int
    key: str
    comment_lines: int


def _comments_directly_above(lines: list[str], entry_idx: int) -> int:
    """Count consecutive `#`-prefixed lines directly above index *entry_idx*
    (no blank line between). `# nocheck:` suppression markers do not count."""
    count = 0
    cursor = entry_idx - 1
    while cursor >= 0:
        line = lines[cursor]
        if _COMMENT_RE.match(line):
            if not _NOCHECK_RE.match(line):
                count += 1
            cursor -= 1
            continue
        break
    return count


def _scan_file(path: Path) -> list[_Violation]:
    lines = read_text(str(path)).splitlines()
    out: list[_Violation] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    for index, line in enumerate(lines):
        match = _KEY_RE.match(line)
        if match is None:
            continue
        n = _comments_directly_above(lines, index)
        if n > 1:
            out.append(_Violation(rel, index + 1, match.group("key"), n))
    return out


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in iter_non_ignored_files(root=str(PROJECT_ROOT))
        if rel.endswith((".env", ".env.j2"))
    ]


class TestEnvSingleLineComments(unittest.TestCase):
    def test_env_entries_have_at_most_one_comment_line_above(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no env files found to scan")

        violations: list[_Violation] = []
        for path in targets:
            violations.extend(_scan_file(path))

        if violations:
            grouped: dict[str, list[_Violation]] = {}
            for v in violations:
                grouped.setdefault(v.file, []).append(v)
            lines = [
                f"Env entries with multi-line comment block "
                f"({len(violations)} violations across {len(grouped)} file(s)):",
                "",
                "Env entries (`KEY=value`) must be preceded by AT MOST one `# ...` comment line on the immediately preceding line. Collapse multi-line blocks to a single one-line WHY comment.",
                "",
                "Offenders:",
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(
                    f"    line {v.line_no} ({v.key}): {v.comment_lines} comment lines above"
                    for v in vs
                )
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
