from __future__ import annotations

import json
from functools import cache
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT

from .csvio import to_csv_string

if TYPE_CHECKING:
    from .model import RoleRuntime

FORMATS = ("table", "markdown", "csv", "json")


@cache
def _known_roles() -> frozenset[str]:
    """Role ids from the repository's roles/ tree; empty when the renderer
    runs outside a checkout (every row then counts as a role)."""
    roles_dir = PROJECT_ROOT / "roles"
    if not roles_dir.is_dir():
        return frozenset()
    return frozenset(p.name for p in roles_dir.iterdir() if p.is_dir())


def _is_role(name: str) -> bool:
    known = _known_roles()
    return name in known if known else True


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


_HOST_CELL = {"executed": "🟢", "skipped": "🔵", "failed": "🔴"}


def _md_table(rows: list[RoleRuntime], title: str) -> str:
    total_rows = [r for r in rows if r.role == "total"]
    task_rows = [r for r in rows if r.role != "total" and not _is_role(r.role)]
    role_rows = [r for r in rows if r.role != "total" and _is_role(r.role)]
    hosts = sorted({host for r in role_rows for host in r.host_map})
    lines = [
        title,
        "",
        "| # | Type | Name | Duration |" + "".join(f" `{h}` |" for h in hosts),
        "|---|------|------|---------:|" + ":---:|" * len(hosts),
    ]
    empty_cells = " |" * len(hosts)
    idx = 0
    for r in task_rows:
        idx += 1
        lines.append(f"| {idx} | task | `{r.role}` | {r.seconds:.2f}s |{empty_cells}")
    for r in role_rows:
        idx += 1
        cells = "".join(
            f" {_HOST_CELL.get(r.host_map.get(h, ''), '')} |" for h in hosts
        )
        lines.append(f"| {idx} | role | `{r.role}` | {r.seconds:.2f}s |{cells}")
    parsed_sum = sum(r.seconds for r in task_rows + role_rows)
    for r in total_rows:
        lines.append(f"| | **total** | recap | **{r.seconds:.2f}s** |{empty_cells}")
        if abs(parsed_sum - r.seconds) > max(1.0, r.seconds * 0.01):
            lines.append(f"| | ⚠️ | parsed rows sum | {parsed_sum:.2f}s |{empty_cells}")
    return "\n".join(lines) + "\n"


def _markdown(records: list[RoleRuntime]) -> str:
    legend = "Hosts: 🟢 executed · 🔵 skipped · 🔴 failed"
    if records[0].segmented:
        parts = ["## ⏱️ Role runtimes per variant (matrix round)", "", legend, ""]
        parts.extend(
            _md_table(rows, f"### {label}") for label, rows in _grouped(records)
        )
    else:
        parts = ["## ⏱️ Role runtimes", "", legend, ""]
        parts.append(_md_table(records, ""))
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
            "hosts": r.host_map,
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
