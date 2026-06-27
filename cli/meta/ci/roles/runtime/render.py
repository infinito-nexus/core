from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .csvio import to_csv_string

if TYPE_CHECKING:
    from .model import RoleRuntime

FORMATS = ("table", "markdown", "csv", "json")


def _grouped(records: list[RoleRuntime]) -> list[tuple[str, list[RoleRuntime]]]:
    groups: list[tuple[str, list[RoleRuntime]]] = []
    for r in records:
        if not groups or groups[-1][0] != r.segment_label:
            groups.append((r.segment_label, []))
        groups[-1][1].append(r)
    return groups


def _table(records: list[RoleRuntime]) -> str:
    lines: list[str] = []
    for label, rows in _grouped(records):
        width = max(len(r.role) for r in rows)
        lines.append(label)
        for idx, r in enumerate(rows, start=1):
            lines.append(f"{idx:>3}  {r.role:<{width}}  {r.seconds:>9.2f}s")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md_table(rows: list[RoleRuntime], title: str) -> str:
    header = [title, "", "| # | Role | Duration |", "|---|------|---------:|"]
    body = [
        f"| {idx} | `{r.role}` | {r.seconds:.2f}s |"
        for idx, r in enumerate(rows, start=1)
    ]
    return "\n".join(header + body) + "\n"


def _markdown(records: list[RoleRuntime]) -> str:
    if records[0].segmented:
        parts = ["## ⏱️ Role runtimes per variant (matrix round)", ""]
        parts.extend(
            _md_table(rows, f"### {label}") for label, rows in _grouped(records)
        )
    else:
        parts = [_md_table(records, "## ⏱️ Role runtimes")]
    return "\n".join(parts) + "\n"


def _json(records: list[RoleRuntime]) -> str:
    payload = [
        {
            "round": r.round,
            "rounds_total": r.rounds_total,
            "pass": r.pass_num,
            "pass_mode": r.pass_mode,
            "role": r.role,
            "seconds": round(r.seconds, 2),
        }
        for r in records
    ]
    return json.dumps(payload, indent=2) + "\n"


def render(records: list[RoleRuntime], fmt: str = "table") -> str:
    if not records:
        return ""
    if fmt == "csv":
        return to_csv_string(records)
    if fmt == "json":
        return _json(records)
    if fmt == "markdown":
        return _markdown(records)
    return _table(records)
