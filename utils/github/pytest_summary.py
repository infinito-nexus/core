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


def _render_report(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()  # noqa: S314  CI-generated reports, not untrusted input
    except ET.ParseError:
        return f"### 🧪 {path.stem}\n\n_Unparseable junit XML: `{path}`._\n"
    cases = _cases(root)
    if not cases:
        return f"### 🧪 {path.stem}\n\n_No test cases in `{path}`._\n"
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
    lines = [headline, ""]
    failures = [c for c in cases if c[1] in ("failed", "error")]
    if failures:
        lines += ["| Failed test | Duration |", "|---|---:|"]
        lines += [f"| `{name}` | {sec:.2f}s |" for name, _, sec in failures]
        lines.append("")
    lines += [
        "<details>",
        f"<summary>All {len(cases)} tests (slowest first)</summary>",
        "",
        "| Test | Status | Duration |",
        "|---|:---:|---:|",
        *(
            f"| `{name}` | {_STATUS_ICON[status]} | {sec:.2f}s |"
            for name, status, sec in sorted(cases, key=lambda c: -c[2])
        ),
        "",
        "</details>",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(f"Usage: {sys.argv[0]} <reports-dir>\n")
        return 2
    base = Path(sys.argv[1])
    reports = sorted(base.glob("*.xml")) if base.is_dir() else []
    if not reports:
        sys.stdout.write(f"### 🧪 Tests\n\n_No junit reports under `{base}`._\n")
        return 0
    sys.stdout.write("\n\n".join(_render_report(p) for p in reports) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
