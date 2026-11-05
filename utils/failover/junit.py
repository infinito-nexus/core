"""JUnit XML writer for failover suite results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class CaseResult:
    name: str
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None


def write_junit(path: Path, *, suite: str, cases: list[CaseResult]) -> None:
    """Write one ``<testsuites>`` document.

    Args:
        path: output file; parent directories are created.
        suite: test suite name, e.g. ``failover-postgres``.
        cases: one entry per scenario.
    """
    root = ET.Element("testsuites")
    node = ET.SubElement(
        root,
        "testsuite",
        name=suite,
        tests=str(len(cases)),
        failures=str(sum(1 for c in cases if c.failures)),
        skipped=str(sum(1 for c in cases if c.skipped)),
        time=f"{sum(c.seconds for c in cases):.3f}",
    )
    for case in cases:
        element = ET.SubElement(
            node,
            "testcase",
            classname=suite,
            name=case.name,
            time=f"{case.seconds:.3f}",
        )
        if case.skipped:
            ET.SubElement(element, "skipped", message=case.skipped)
        for failure in case.failures:
            ET.SubElement(element, "failure", message=failure).text = failure
        if case.notes:
            ET.SubElement(element, "system-out").text = "\n".join(case.notes)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
