"""Lint: cap Python file length at 500 lines (production code only).

Every production ``.py`` file tracked by the repository (i.e. not
matched by ``.gitignore``) must be at most :data:`MAX_PY_LINES` lines
long. The threshold is a soft architectural cue — a file approaching
the cap is usually doing too many things and is a candidate for a
split.

Files under the top-level ``tests/`` directory are intentionally
excluded: tests cluster fixtures and parametrised cases by feature,
so length here reflects coverage breadth rather than design weight.

Per-file opt-out
----------------

A file may opt out of this cap by including the marker
:data:`NOCHECK_MARKER_REGEX` (matches ``#nocheck`` or ``# nocheck``)
inside the first :data:`NOCHECK_SCAN_LINES` lines — typically the
module docstring or a comment at the top. The opt-out is intentionally
visible at the top of the file so the cost of carrying long modules is
not silently buried.

The walker uses the SPOT helpers in :mod:`utils.cache.files` so the
lint runs in environments where ``.git/`` is not mounted (the
``make exec`` container) and stays consistent with other gitignore-
aware lint tests.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.base import PROJECT_ROOT
from utils.cache.files import iter_non_ignored_files


# A file at this length is generally too coupled / too scope-broad and
# should be split. Bumping this number requires a corresponding cleanup
# pass — do not raise it just to silence the linter.
MAX_PY_LINES: int = 500

# Number of leading lines to scan for the per-file opt-out marker. Kept
# small so the marker has to live near the top of the file (visible,
# not buried) and so the scan stays cheap.
NOCHECK_SCAN_LINES: int = 30

# Matches `#nocheck` and `# nocheck`. The trailing word boundary keeps
# unrelated tokens (`#nocheckpoint`, `#nochecksum`) from accidentally
# silencing the lint.
NOCHECK_MARKER_REGEX = re.compile(r"#\s*nocheck\b")


def _line_count(path: Path) -> int:
    # Read as bytes + count newlines so the check works on files that
    # accidentally ship with a non-UTF-8 byte (lint must not fail on a
    # decode error before reporting the size violation).
    with path.open("rb") as fh:
        data = fh.read()
    if not data:
        return 0
    n = data.count(b"\n")
    # Match `wc -l` only when the file ends with a newline; a file that
    # ends without a final newline still has that last "line".
    return n if data.endswith(b"\n") else n + 1


def _has_nocheck_marker(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head_lines: list[str] = []
            for idx, line in enumerate(fh):
                if idx >= NOCHECK_SCAN_LINES:
                    break
                head_lines.append(line)
    except OSError:
        return False
    head = "".join(head_lines)
    return bool(NOCHECK_MARKER_REGEX.search(head))


class TestPythonFileSize(unittest.TestCase):
    def test_python_files_at_or_below_max_lines(self):
        root = PROJECT_ROOT
        offenders: list[tuple[str, int]] = []
        for path_str in iter_non_ignored_files(extensions=(".py",), exclude_tests=True):
            path = Path(path_str)
            lines = _line_count(path)
            if lines <= MAX_PY_LINES:
                continue
            if _has_nocheck_marker(path):
                continue
            rel = path.relative_to(root).as_posix()
            offenders.append((rel, lines))

        if offenders:
            offenders.sort(key=lambda item: (-item[1], item[0]))
            self.fail(
                f"Python files exceeding {MAX_PY_LINES} lines "
                f"({len(offenders)}):\n"
                + "\n".join(f"  - {rel} ({lines} lines)" for rel, lines in offenders)
                + "\n\nSplit the file or move sections into focused modules. "
                "Raising MAX_PY_LINES requires a corresponding cleanup pass."
            )


if __name__ == "__main__":
    unittest.main()
