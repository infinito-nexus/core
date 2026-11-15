"""The ``nocheck: swarm-loopback-port`` marker of ``utils/roles/swarm_loopback.py``.

Where a marker sits, which scope it covers and which reasons it accepts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.annotations.suppress import marker_reason
from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

RULE = "swarm-loopback-port"
OPEN = "open"
CATEGORIES = ("exec", "overlay", "netns", "unused", OPEN)
FILE_SCOPE = "file"
MIN_REASON = 10
_CITATION = re.compile(r"\b(0\d\d)\s*:(\d+)\b")
_OPEN_CRITERION = "- [ ]"
_COMMENT_LINE = re.compile(r"^\s*(?:\{#.*#\}|#.*)\s*$")


def attached_marker(lines: Sequence[str], line_no: int) -> tuple[int, str] | None:
    """Returns the line and reason of the marker that covers *line_no*, if any.

    The marker sits on the construct's own line or on any line of the comment
    block directly above it, Jinja ``{# #}`` or ``#``.

    Args:
        lines: the file's lines.
        line_no: 1-based line of the construct.
    """
    candidates = [line_no - 1]
    while candidates[-1] > 0 and _COMMENT_LINE.match(lines[candidates[-1] - 1]):
        candidates.append(candidates[-1] - 1)
    for index in candidates:
        reason = marker_reason(lines[index], RULE)
        if reason is not None:
            return index + 1, reason.removesuffix("#}").strip()
    return None


def marker_scope(reason: str) -> tuple[bool, str]:
    """Returns whether a marker covers its whole file, and its reason without the scope word.

    Args:
        reason: the text after the marker's rule key.
    """
    scope, _, rest = reason.strip().partition(" ")
    if scope == FILE_SCOPE:
        return True, rest.strip()
    return False, reason.strip()


def _citation_problem(requirements_dir: Path, number: str, line: int) -> str | None:
    documents = sorted(requirements_dir.glob(f"{number}-*.md"))
    if len(documents) != 1:
        return f"cites {number} :{line}, but no single docs/requirements/{number}-*.md exists"
    rows = read_text(str(documents[0])).splitlines()
    if not 0 < line <= len(rows) or not rows[line - 1].startswith(_OPEN_CRITERION):
        return (
            f"cites {number} :{line}, which is no open criterion of {documents[0].name}"
        )
    return None


def reason_problem(reason: str, requirements_dir: Path) -> str | None:
    """Returns why a marker's reason is not accepted, or None.

    Args:
        reason: the text after the marker's rule key, without the ``file`` scope word.
        requirements_dir: the ``docs/requirements`` directory an ``open`` reason cites.
    """
    category, _, prose = reason.partition(" ")
    if category not in CATEGORIES:
        return f"names no category of {', '.join(CATEGORIES)}"
    if len(prose.strip()) < MIN_REASON:
        return "states no reason after its category"
    if category != OPEN:
        return None
    citations = _CITATION.findall(prose)
    if not citations:
        return "is open but cites no criterion (NNN :LINE of docs/requirements/NNN-*.md) that tracks it"
    for number, line in citations:
        problem = _citation_problem(requirements_dir, number, int(line))
        if problem:
            return problem
    return None
