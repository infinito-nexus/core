"""Locate a declared pin inside the file that carries it.

A pin lives either in the block of its entity in ``meta/services.yml`` or at
the root of a ``meta/addons/<id>.yml``. The updater has to find its line to
rewrite exactly that one, so the search is textual: parsing and re-emitting
the YAML would reformat every other line of the file.
"""

from __future__ import annotations

import re


def key_line(lines: list[str], entity: str, key: str) -> int | None:
    """Return the 1-indexed line of ``key`` inside the block of ``entity``.

    Args:
        lines: lines of the file that carries the pin.
        entity: top-level key whose block holds the pin.
        key: pinned key.
    """
    inside = False
    for number, line in enumerate(lines, start=1):
        if re.match(rf"^{re.escape(entity)}\s*:", line):
            inside = True
            continue
        if inside and line and not line[0].isspace():
            inside = False
        if inside and re.match(rf"^\s+{re.escape(key)}\s*:", line):
            return number
    return None


def top_level_line(lines: list[str], key: str) -> int | None:
    """Return the 1-indexed line of ``key`` at the root of an addon file.

    Args:
        lines: lines of the file that carries the pin.
        key: pinned key.
    """
    for number, line in enumerate(lines, start=1):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            return number
    return None


def archive_index(lines: list[str]) -> int | None:
    """Return the 0-indexed line of ``config.archive`` in an addon file.

    Args:
        lines: lines of the file that carries the pin.
    """
    for index, line in enumerate(lines):
        if re.match(r"^\s+archive\s*:", line):
            return index
    return None
