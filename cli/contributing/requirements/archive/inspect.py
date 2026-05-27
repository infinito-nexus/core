"""Parse a single requirement file: H1 heading and task-list completeness."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

H1_RE = re.compile(r"^#\s+(?P<title>\S.*?)\s*$")
UNCHECKED_TASK_RE = re.compile(r"^\s*[-*+]\s+\[\s\]\s")


def extract_h1(path: Path) -> str | None:
    """Return the first H1 title in *path* or ``None`` if there is none."""
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                match = H1_RE.match(line.rstrip("\n"))
                if match:
                    return match.group("title")
    except OSError:
        return None
    return None


def count_unchecked_items(path: Path) -> int:
    """Return the number of ``- [ ]`` task-list markers anywhere in *path*.

    A non-zero count means the requirement is not yet fully implemented
    and MUST NOT be archived.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            return sum(1 for line in fh if UNCHECKED_TASK_RE.match(line))
    except OSError:
        return 0
