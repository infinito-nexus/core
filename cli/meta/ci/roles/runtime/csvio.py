from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import IO

from .model import RoleRuntime

CSV_HEADER = ["round", "rounds_total", "pass", "pass_mode", "role", "seconds", "hosts"]


def _to_row(r: RoleRuntime) -> list[str]:
    return [
        r.round,
        r.rounds_total,
        r.pass_num,
        r.pass_mode,
        r.role,
        f"{r.seconds:.2f}",
        r.hosts,
    ]


def dump_csv(records: list[RoleRuntime], fh: IO[str]) -> None:
    writer = csv.writer(fh)
    writer.writerow(CSV_HEADER)
    for r in records:
        writer.writerow(_to_row(r))


def to_csv_string(records: list[RoleRuntime]) -> str:
    buf = io.StringIO()
    dump_csv(records, buf)
    return buf.getvalue()


def write_csv(path: str | Path, records: list[RoleRuntime]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        dump_csv(records, fh)


def read_csv(path: str | Path) -> list[RoleRuntime]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return [
            RoleRuntime(
                role=row["role"],
                seconds=float(row["seconds"]),
                round=row.get("round", ""),
                rounds_total=row.get("rounds_total", ""),
                pass_num=row.get("pass", ""),
                pass_mode=row.get("pass_mode", ""),
                hosts=row.get("hosts", "") or "",
            )
            for row in csv.DictReader(fh)
        ]
