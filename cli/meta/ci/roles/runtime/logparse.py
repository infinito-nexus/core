from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .model import RoleRuntime

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
LINE_RE = re.compile(
    r"^(?:.*\bINFO\|\s+)?(?P<name>\S.*?)\s-{2,}\s+(?P<seconds>\d+(?:\.\d+)?)s\s*$"
)
SEGMENT_RE = re.compile(
    r"matrix-deploy: round (?P<round>\d+)/(?P<rounds>\d+).*?"
    r"PASS (?P<pass>\d+) \((?P<mode>sync|async)\)"
)


def _role_time(line: str) -> tuple[str, float] | None:
    """Return (role, seconds) for a profile_roles summary line, else None.

    Drops the `total` line and `<role> : <task>` profile_tasks entries so only
    real per-role rows survive.
    """
    match = LINE_RE.match(line)
    if not match:
        return None
    name = match.group("name").strip()
    if not name or name.lower() == "total" or " : " in name:
        return None
    try:
        return name, float(match.group("seconds"))
    except ValueError:
        return None


def _sorted(totals: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def parse_log(log_path: str | Path) -> list[RoleRuntime]:
    """Ansible run log -> records.

    When the log carries the matrix-deploy round/pass markers, the result is
    segmented (one block of records per variant round + pass). Otherwise a
    single combined block is returned. Raises FileNotFoundError when the log
    is absent (the caller turns that into a hard failure).
    """
    path = Path(log_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    segments: list[tuple[tuple[str, str, str, str], dict[str, float]]] = []
    current: dict[str, float] | None = None
    combined: dict[str, float] = defaultdict(float)
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = ANSI_RE.sub("", raw).rstrip()
            marker = SEGMENT_RE.search(line)
            if marker:
                meta = (
                    marker.group("round"),
                    marker.group("rounds"),
                    marker.group("pass"),
                    marker.group("mode"),
                )
                current = defaultdict(float)
                segments.append((meta, current))
                continue
            row = _role_time(line)
            if not row:
                continue
            combined[row[0]] += row[1]
            if current is not None:
                current[row[0]] += row[1]

    records: list[RoleRuntime] = []
    for (rnd, rounds, pass_num, mode), totals in segments:
        for role, seconds in _sorted(totals):
            records.append(RoleRuntime(role, seconds, rnd, rounds, pass_num, mode))
    if records:
        return records
    return [RoleRuntime(role, seconds) for role, seconds in _sorted(combined)]
