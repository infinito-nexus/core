"""Lint guard: `.sh` files MUST NOT swallow failures with ``|| true``.

``cmd || true`` unconditionally discards the exit code of ``cmd``, so a
real regression (a command that starts failing) passes silently. Under
``set -euo pipefail`` that is the whole point — but it also masks the
failures you *do* want to see. Prefer catching the specific tolerated
condition instead (inspect the output / rc and re-``exit`` on anything
unexpected), or gate the command on a precondition.

Suppress on a per-line basis with a same-line
``# nocheck: shell-or-true -- <reason>`` marker. The existing corpus is
grandfathered with that marker: those cases have worked in practice and
there was no time to narrow each to its exact tolerated error; the guard
exists to stop *new* blanket ``|| true`` from creeping in.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

# ``... || true`` (also ``|| :``), optionally followed by a comment.
_OR_TRUE_RE = re.compile(r"\|\|\s*(?:true|:)\s*(?:#|;|$)")
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    detail: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
        ],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _scan_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(rel, 0, str(exc))]

    for idx, raw in enumerate(text.splitlines(), 1):
        if _NOCHECK_RE.search(raw):
            continue
        if _OR_TRUE_RE.search(raw):
            violations.append(
                Violation(
                    rel,
                    idx,
                    "`|| true` unconditionally swallows the exit code; catch "
                    "the specific tolerated error and re-exit on anything else, "
                    "or suppress with "
                    "`# nocheck: shell-or-true -- <reason>`",
                )
            )
    return violations


def _scan_targets() -> list[Path]:
    return [PROJECT_ROOT / rel for rel in _git_ls_files() if rel.endswith(".sh")]


class TestShellNoOrTrue(unittest.TestCase):
    def test_shell_files_dont_swallow_failures_with_or_true(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no .sh files found to scan")
        all_violations: list[Violation] = []
        for path in targets:
            all_violations.extend(_scan_file(path))
        if all_violations:
            grouped: dict[str, list[Violation]] = {}
            for v in all_violations:
                grouped.setdefault(v.file, []).append(v)
            lines = [
                f"Unmarked `|| true` in .sh "
                f"({len(all_violations)} violations across "
                f"{len(grouped)} file(s)):",
                "",
                "`cmd || true` discards cmd's exit code, so a future "
                "regression passes silently. Catch the specific tolerated "
                "error instead, or suppress per line with "
                "`# nocheck: shell-or-true -- <reason>`.",
                "",
                "Offenders:",
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(f"    line {v.line_no}: {v.detail}" for v in vs)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
