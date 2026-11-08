"""Opt-in open subtrees of the role contract.

A mapping key in ``meta/services.yml`` that carries
``# nocheck: inventory-open-subtree <reason>`` on its own line, or on the
comment line directly above it, lets the inventory set any child key under
it. A marker without a reason opens nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils.annotations.suppress import marker_reason
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

RULE = "inventory-open-subtree"
MIN_REASON_CHARS = 10
LIST_SEGMENT = "[]"
_KEY_LINE = re.compile(
    r"^\s*(?P<key>'[^']+'|\"[^\"]+\"|[^\s#:'\"-][^:#]*?)\s*:(?:\s|$)"
)
_LIST_ITEM = re.compile(r"^\s*-(?:\s|$)")


def _key_paths(lines: list[str]) -> dict[int, str]:
    """Map each key line of a ``meta/services.yml`` to its materialised path.

    Args:
        lines: the file's lines.

    Returns:
        1-based line number mapped to ``services.<key>.<key>...``. Keys
        inside a list item carry a ``[]`` segment no inventory key matches.
    """
    paths: dict[int, str] = {}
    stack: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if _LIST_ITEM.match(line):
            stack.append((indent, LIST_SEGMENT))
            continue
        key = _KEY_LINE.match(line)
        if key is None:
            continue
        stack.append((indent, key.group("key").strip("'\"")))
        paths[number] = ".".join(["services", *(segment for _, segment in stack)])
    return paths


def markers(lines: list[str]) -> list[tuple[int, str, str]]:
    """List every ``inventory-open-subtree`` marker of a ``meta/services.yml``.

    Args:
        lines: the file's lines.

    Returns:
        ``(line_no, path, reason)`` per marker. ``path`` is the materialised
        path of the marked key, empty when the marker sits on no key.
    """
    paths = _key_paths(lines)
    found: list[tuple[int, str, str]] = []
    for number, line in enumerate(lines, start=1):
        reason = marker_reason(line, RULE)
        if reason is None:
            continue
        target = number
        if number not in paths and line.strip().startswith("#"):
            target = number + 1
        found.append((number, paths.get(target, ""), reason))
    return found


def open_paths(lines: list[str]) -> set[str]:
    """Return the materialised paths a ``meta/services.yml`` opens.

    Args:
        lines: the file's lines.

    Returns:
        Paths of keys whose marker states a reason of at least
        ``MIN_REASON_CHARS`` characters.
    """
    return {
        path
        for _, path, reason in markers(lines)
        if path and LIST_SEGMENT not in path and len(reason) >= MIN_REASON_CHARS
    }


def open_subtree_paths(roles_dir: str | Path) -> dict[str, set[str]]:
    """Map each role to the open subtrees its ``meta/services.yml`` declares.

    Args:
        roles_dir: the repository's roles directory.

    Returns:
        Application id mapped to its opened paths; roles without any are absent.
    """
    result: dict[str, set[str]] = {}
    for services in sorted(Path(roles_dir).glob(f"*/{ROLE_FILE_META_SERVICES}")):
        paths = open_paths(read_text(str(services)).splitlines())
        if paths:
            result[services.parent.parent.name] = paths
    return result
