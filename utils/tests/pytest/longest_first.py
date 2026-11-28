"""Pytest plugin that hands the slowest ``loadscope`` scopes out first."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.nodes import Item


def junit_classname(nodeid: str) -> str:
    """
    Args:
        nodeid: a collected item's node id.

    Returns:
        The ``classname`` pytest's JUnit report files the item under.
    """
    names = nodeid.split("::")
    names[0] = names[0].replace("/", ".").removesuffix(".py")
    return ".".join(names[:-1])


def scope_durations(report: Path) -> dict[str, float]:
    """
    Args:
        report: a JUnit XML report of an earlier run.

    Returns:
        The summed case time per ``classname``; empty when the report is
        missing or unreadable.
    """
    durations: dict[str, float] = defaultdict(float)
    try:
        cases = ET.parse(report).iter("testcase")  # noqa: S314  the run's own JUnit report, not untrusted input
        for case in cases:
            durations[case.get("classname") or ""] += float(case.get("time") or 0)
    except (OSError, ET.ParseError, ValueError):
        return {}
    return dict(durations)


def longest_first(items: list[Item], durations: dict[str, float]) -> list[Item]:
    """
    Args:
        items: the collected items in collection order.
        durations: the summed duration per JUnit ``classname``.

    Returns:
        The same items, scopes without a recorded duration first, then the
        recorded scopes by descending duration.
    """
    first_seen: dict[str, int] = {}
    for index, item in enumerate(items):
        first_seen.setdefault(junit_classname(item.nodeid), index)

    def key(item: Item) -> tuple[float, int]:
        scope = junit_classname(item.nodeid)
        return (-durations.get(scope, float("inf")), first_seen[scope])

    return sorted(items, key=key)


def item_counts(items: list[Item]) -> dict[str, float]:
    """
    Args:
        items: the collected items.

    Returns:
        The number of items per JUnit ``classname``, the order
        ``--loadscope-reorder`` would have used.
    """
    counts: dict[str, float] = defaultdict(float)
    for item in items:
        counts[junit_classname(item.nodeid)] += 1
    return dict(counts)


def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
    report = config.getoption("xmlpath", None)
    durations = scope_durations(Path(report)) if report else {}
    items[:] = longest_first(items, durations or item_counts(items))
