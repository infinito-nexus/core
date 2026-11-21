"""JUnit reader: pull the first failing testcase out of a JUnit XML report as
its name, its failure message and its captured ``system-out``, so a routine
reports the one failure that matters instead of the whole report.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def failures(junit_xml: str) -> list[dict]:
    """Return ``{"name", "message", "system_out"}`` of every testcase that
    carries a ``<failure>`` or ``<error>`` child, in report order.

    The message is the fault element's ``message`` attribute, falling back to
    its text body; ``system_out`` is the testcase's ``<system-out>`` text.

    Args:
        junit_xml: the JUnit XML report as a string.
    """
    root = ET.fromstring(junit_xml)  # noqa: S314  CI-generated reports, not untrusted input
    found: list[dict] = []
    for testcase in root.iter("testcase"):
        fault = testcase.find("failure")
        if fault is None:
            fault = testcase.find("error")
        if fault is None:
            continue
        message = fault.get("message")
        if message is None:
            message = (fault.text or "").strip()
        system_out = testcase.find("system-out")
        found.append(
            {
                "name": testcase.get("name"),
                "message": message,
                "system_out": (system_out.text or "").strip()
                if system_out is not None
                else "",
            }
        )
    return found


def first_failure(junit_xml: str) -> dict | None:
    """Return the first entry of ``failures``, or ``None`` when every case
    passed.

    Args:
        junit_xml: the JUnit XML report as a string.
    """
    found = failures(junit_xml)
    return found[0] if found else None
