"""Lint: every ``meta/packages.yml`` is sorted ascending.

Package ids, the distro keys under each id and every list of concrete
names read in ascending order, so a reader finds an entry by position and
a diff shows only what actually changed.
"""

from __future__ import annotations

import itertools
import re
import unittest

from utils.cache.files import read_text
from utils.packages.registry import iter_package_files

from . import PROJECT_ROOT

_ID_RE = re.compile(r"^(?P<key>[A-Za-z0-9_.@+-]+):")
_DISTRO_RE = re.compile(r"^  (?P<key>[A-Za-z0-9_.-]+):")
_ITEM_RE = re.compile(r"^(?P<indent> +)- (?P<name>\S+)")


def _first_descent(values: list[str]) -> tuple[str, str] | None:
    """First adjacent pair that is out of ascending order."""
    for previous, current in itertools.pairwise(values):
        if current < previous:
            return previous, current
    return None


def _unsorted_runs(path: str) -> list[tuple[str, str, str]]:
    """Every ascending-order violation in one declaration file."""
    findings: list[tuple[str, str, str]] = []
    ids: list[str] = []
    distros: list[str] = []
    items: list[str] = []
    item_indent = ""

    def flush(scope: str, values: list[str]) -> None:
        pair = _first_descent(values)
        if pair:
            findings.append((scope, pair[0], pair[1]))
        values.clear()

    for line in read_text(path).splitlines():
        item = _ITEM_RE.match(line)
        if item and item.group("indent") == item_indent:
            items.append(item.group("name"))
            continue

        flush("name", items)
        if item:
            item_indent = item.group("indent")
            items.append(item.group("name"))
            continue

        item_indent = ""
        if _ID_RE.match(line):
            flush("distro key", distros)
            ids.append(_ID_RE.match(line).group("key"))
        elif _DISTRO_RE.match(line):
            distros.append(_DISTRO_RE.match(line).group("key"))

    flush("name", items)
    flush("distro key", distros)
    flush("package id", ids)
    return findings


class TestPackagesSorted(unittest.TestCase):
    def test_declarations_are_sorted_ascending(self) -> None:
        offenders: list[str] = []
        for _role, path in iter_package_files(PROJECT_ROOT):
            rel = path.relative_to(PROJECT_ROOT)
            offenders.extend(
                f"{rel}: {scope} '{later}' follows '{earlier}'"
                for scope, earlier, later in _unsorted_runs(str(path))
            )

        if offenders:
            self.fail(
                f"{len(offenders)} package declaration(s) are not sorted "
                "ascending. Package ids, their distro keys and every list of "
                "names read in ascending order:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
