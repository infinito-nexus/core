"""Render pytest junit-xml reports as a GitHub step-summary section.

Usage: python3 utils/github/pytest_summary.py <reports-dir>  # nocheck: self-path-reference

Reads every ``*.xml`` under <reports-dir> (one per test target, written
by scripts/tests/code/run.sh via ``--junitxml``). Per report: a headline
with the pass/fail/skip counts and total time, failures rendered opened,
and the full per-test table (name, status, duration) collapsed in a
details block, slowest first.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SUMMARY_BUDGET = 1024 * 1024 - 8 * 1024
_STATUS_ICON = {"passed": "🟢", "failed": "🔴", "error": "🔴", "skipped": "🔵"}


def _case_status(case: ET.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def _cases(root: ET.Element) -> list[tuple[str, str, float]]:
    cases = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        full = f"{classname}::{name}" if classname else name
        cases.append((full, _case_status(case), float(case.get("time", 0) or 0)))
    return cases


def _load(path: Path) -> tuple[list[str], list[str], list[str]]:
    try:
        root = ET.parse(path).getroot()  # noqa: S314  CI-generated reports, not untrusted input
    except ET.ParseError:
        return (
            [f"### 🧪 {path.stem}", "", f"_Unparseable junit XML: `{path}`._"],
            [],
            [],
        )
    cases = _cases(root)
    if not cases:
        return [f"### 🧪 {path.stem}", "", f"_No test cases in `{path}`._"], [], []
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for _, status, _ in cases:
        counts[status] += 1
    total_time = sum(seconds for _, _, seconds in cases)
    failed = counts["failed"] + counts["error"]
    headline = (
        f"### 🧪 {path.stem} — "
        f"🟢 {counts['passed']} · 🔴 {failed} · 🔵 {counts['skipped']} · "
        f"{total_time:.1f}s"
    )
    failures = [
        f"| `{name}` | {sec:.2f}s |"
        for name, status, sec in cases
        if status in ("failed", "error")
    ]
    rows = [
        f"| `{name}` | {_STATUS_ICON[status]} | {sec:.2f}s |"
        for name, status, sec in sorted(cases, key=lambda c: -c[2])
    ]
    return [headline, ""], failures, rows


def _assemble(
    report: tuple[list[str], list[str], list[str]], keep_failures: int, keep_rows: int
) -> str:
    """Args:
        report: (head lines, failure rows, all-test rows) from ``_load``.
        keep_failures: how many failure rows to render.
        keep_rows: how many all-test rows to render, slowest first.

    Returns:
        The markdown section, ending with a newline.
    """
    head, failures, rows = report
    lines = list(head)
    if failures:
        lines += ["| Failed test | Duration |", "|---|---:|", *failures[:keep_failures]]
        if keep_failures < len(failures):
            lines.append(
                f"| _{len(failures) - keep_failures} more failed tests left out_ | |"
            )
        lines.append("")
    if rows:
        lines += [
            "<details>",
            f"<summary>All {len(rows)} tests (slowest first)</summary>",
            "",
            "| Test | Status | Duration |",
            "|---|:---:|---:|",
            *rows[:keep_rows],
        ]
        if keep_rows < len(rows):
            lines.append(f"| _{len(rows) - keep_rows} faster tests left out_ | | |")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def _render_report(path: Path) -> str:
    report = _load(path)
    return _assemble(report, len(report[1]), len(report[2]))


def _bytes(lines: list[str]) -> int:
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


def _fair_share(demands: list[int], total: int) -> list[int]:
    """Args:
        demands: bytes each consumer would like.
        total: bytes available overall.

    Returns:
        The allowance per consumer, in input order.
    """
    shares = [0] * len(demands)
    remaining = max(total, 0)
    order = sorted(range(len(demands)), key=lambda i: demands[i])
    for position, i in enumerate(order):
        shares[i] = min(demands[i], remaining // (len(order) - position))
        remaining -= shares[i]
    return shares


def _fit(lines: list[str], allowance: int) -> int:
    used = 0
    for count, line in enumerate(lines):
        used += len(line.encode("utf-8")) + 1
        if used > allowance:
            return count
    return len(lines)


def _keeps(
    loaded: list[tuple[list[str], list[str], list[str]]], available: int
) -> tuple[list[int], list[int]]:
    """Args:
        loaded: one ``_load`` result per report.
        available: bytes the reports may fill together.

    Returns:
        ``(failure_keep, row_keep)``: per report, how many failure rows and
        how many all-test rows fit.
    """
    fixed = [len(_assemble(r, 0, 0).encode("utf-8")) for r in loaded]
    failure_keep = [
        _fit(r[1], a)
        for r, a in zip(
            loaded,
            _fair_share([_bytes(r[1]) for r in loaded], available - sum(fixed)),
            strict=True,
        )
    ]
    left = (
        available
        - sum(fixed)
        - sum(_bytes(r[1][:k]) for r, k in zip(loaded, failure_keep, strict=True))
    )
    row_keep = [
        _fit(r[2], a)
        for r, a in zip(
            loaded, _fair_share([_bytes(r[2]) for r in loaded], left), strict=True
        )
    ]
    return failure_keep, row_keep


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(f"Usage: {sys.argv[0]} <reports-dir>\n")
        return 2
    base = Path(sys.argv[1])
    reports = sorted(base.glob("*.xml")) if base.is_dir() else []
    if not reports:
        sys.stdout.write(f"### 🧪 Tests\n\n_No junit reports under `{base}`._\n")
        return 0
    loaded = [_load(p) for p in reports]
    failure_keep, row_keep = _keeps(loaded, _SUMMARY_BUDGET - 2 * (len(loaded) - 1) - 1)
    sys.stdout.write(
        "\n\n".join(
            _assemble(r, f, k)
            for r, f, k in zip(loaded, failure_keep, row_keep, strict=True)
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
