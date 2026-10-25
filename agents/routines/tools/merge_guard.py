"""Merge guard: after a merge, compare the result against both parents and
report what the merge dropped. ``lost_markers`` finds the ``# nocheck:``
markers, ``- name:`` tasks and ``when:`` clauses that a parent carried but the
merged text no longer does; ``version_pin_drift`` names the pins whose version
differs between the two parents, so the merge's pin choice gets a human look.
"""

from __future__ import annotations

import re

_NOCHECK = re.compile(r"#\s*nocheck:\s*(.+)")
_TASK = re.compile(r"-\s*name:\s*(.+)")
_WHEN = re.compile(r"\bwhen:\s*(.+)")
_PIP_PIN = re.compile(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.*+-]+)")
_IMAGE_PIN = re.compile(r"image:\s*([A-Za-z0-9_./-]+):([A-Za-z0-9_.*+-]+)")


def _items(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [stripped for match in pattern.finditer(text) if (stripped := match.group(1).strip())]


def lost_markers(merged: str, parent_a: str, parent_b: str) -> dict[str, list[str]]:
    """Return the markers present in either parent but absent from ``merged``,
    keyed ``"nocheck"``, ``"tasks"`` and ``"when"``; each value lists the lost
    items in first-seen order without duplicates.

    Args:
        merged: the merged text to audit.
        parent_a: the first merge parent.
        parent_b: the second merge parent.
    """
    result: dict[str, list[str]] = {}
    for key, pattern in (("nocheck", _NOCHECK), ("tasks", _TASK), ("when", _WHEN)):
        present = dict.fromkeys(_items(parent_a, pattern) + _items(parent_b, pattern))
        merged_items = set(_items(merged, pattern))
        result[key] = [item for item in present if item not in merged_items]
    return result


def _pins(text: str) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for name, version in _PIP_PIN.findall(text) + _IMAGE_PIN.findall(text):
        pins.setdefault(name, set()).add(version)
    return pins


def version_pin_drift(parent_a: str, parent_b: str) -> list[str]:
    """Return, sorted, the names of the version pins that both parents carry
    with a differing version (e.g. ``foo==1.2`` vs ``foo==1.3``, or
    ``image: x:1.2`` vs ``image: x:1.4``).

    Args:
        parent_a: the first merge parent.
        parent_b: the second merge parent.
    """
    pins_a = _pins(parent_a)
    pins_b = _pins(parent_b)
    return sorted(
        name for name in pins_a if name in pins_b and pins_a[name] != pins_b[name]
    )
