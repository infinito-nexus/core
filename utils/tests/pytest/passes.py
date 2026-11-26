"""Pytest plugin that prints the ``-rP`` PASSES section in linear time.

pytest's own ``-rP`` summary finds each passed test's teardown reports by
scanning every setup and teardown report of the session, so it grows with the
square of the test count and costs minutes on the unit suite. Loaded with
``-p utils.tests.pytest.passes`` instead of ``-rP``, this plugin prints the same
section, built from the same reports in the same order, and indexes the
teardown reports once.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from _pytest.config import Config
    from _pytest.reports import TestReport
    from _pytest.terminal import TerminalReporter

TITLE = "PASSES"
MASK_COMMAND = "::add-mask::"


def _shown(reports: Iterable[TestReport]) -> list[TestReport]:
    return [report for report in reports if not hasattr(report, "_pdbshown")]


def teardowns_by_node(reports: Iterable[TestReport]) -> dict[str, list[TestReport]]:
    """
    Args:
        reports: the reports pytest files under the empty status, the passed
            setup and teardown phases.

    Returns:
        The teardown reports, grouped by node id, each group in report order.
    """
    grouped: dict[str, list[TestReport]] = defaultdict(list)
    for report in reports:
        if report.when == "teardown":
            grouped[report.nodeid].append(report)
    return grouped


def without_masks(content: str) -> str:
    """
    Args:
        content: one captured output section of a passed test.

    Returns:
        The section without its ``::add-mask::`` workflow command lines.
    """
    return "\n".join(
        line
        for line in content.removesuffix("\n").split("\n")
        if not line.lstrip().startswith(MASK_COMMAND)
    )


def _write_sections(config: Config, report: TestReport, *, teardown_only: bool) -> None:
    showcapture = config.option.showcapture
    if showcapture == "no":
        return
    writer = config.get_terminal_writer()
    for name, content in report.sections:
        if showcapture != "all" and showcapture not in name:
            continue
        if teardown_only and "teardown" not in name:
            continue
        text = without_masks(content)
        if not text:
            continue
        writer.sep("-", name)
        writer.line(text)


def pytest_terminal_summary(terminalreporter: TerminalReporter, config: Config) -> None:
    if hasattr(config, "workerinput") or config.option.tbstyle == "no":
        return
    passed = _shown(terminalreporter.stats.get("passed", ()))
    if not passed:
        return
    teardowns = teardowns_by_node(_shown(terminalreporter.stats.get("", ())))
    terminalreporter.write_sep("=", TITLE)
    for report in passed:
        if report.sections:
            terminalreporter.write_sep(
                "_", report.head_line or "test session", green=True, bold=True
            )
            report.toterminal(config.get_terminal_writer())
            _write_sections(config, report, teardown_only=False)
        for teardown in teardowns.get(report.nodeid, ()):
            _write_sections(config, teardown, teardown_only=True)
