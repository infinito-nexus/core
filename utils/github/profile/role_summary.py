"""Parse an Ansible `profile_roles` log and write the per-role runtimes to `$GITHUB_STEP_SUMMARY`."""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
LINE_RE = re.compile(
    r"^(?:.*\bINFO\|\s+)?(?P<name>\S.*?)\s-{2,}\s+(?P<seconds>\d+(?:\.\d+)?)s\s*$"
)


def _strip_ansi(line: str) -> str:
    return ANSI_RE.sub("", line)


def parse_role_times(log_path: Path) -> list[tuple[str, float]]:
    totals: dict[str, float] = defaultdict(float)
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = _strip_ansi(raw).rstrip()
            match = LINE_RE.match(line)
            if not match:
                continue
            name = match.group("name").strip()
            if not name or name.lower() == "total" or " : " in name:
                continue
            try:
                seconds = float(match.group("seconds"))
            except ValueError:
                continue
            totals[name] += seconds
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def _format_table(rows: list[tuple[str, float]]) -> str:
    header = [
        "## ⏱️ Role runtimes",
        "",
        "| # | Role | Duration |",
        "|---|------|---------:|",
    ]
    body = [
        f"| {idx} | `{name}` | {seconds:.2f}s |"
        for idx, (name, seconds) in enumerate(rows, start=1)
    ]
    return "\n".join(header + body) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: role_summary.py <ansible-log>", file=sys.stderr)
        return 2
    log_path = Path(argv[1])
    if not log_path.is_file():
        print(f"[role_summary] log not found: {log_path}", file=sys.stderr)
        return 0
    rows = parse_role_times(log_path)
    if not rows:
        print("[role_summary] no profile_roles entries found", file=sys.stderr)
        return 0
    table = _format_table(rows)
    print(table)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
