from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .model import HOST_EXECUTED, HOST_FAILED, HOST_SKIPPED, RoleRuntime

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RUNNER_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z ")
LINE_RE = re.compile(
    r"^(?:.*\bINFO\|\s+)?(?P<name>\S.*?)\s-{2,}\s+(?P<seconds>\d+(?:\.\d+)?)s\s*$"
)
SEGMENT_RE = re.compile(
    r"matrix-deploy: round (?P<round>\d+)/(?P<rounds>\d+).*?"
    r"PASS (?P<pass>\d+) \((?P<mode>sync|async)\)"
)
ROLES_RECAP_RE = re.compile(r"^ROLES RECAP \*+")
OTHER_RECAP_RE = re.compile(r"^(TASKS|PLAY|PLAYBOOK) RECAP \*+")
TOTAL_ROW = "total"
TASK_RE = re.compile(r"TASK \[(?P<role>[^\]]+?) : [^\]]*\] \*{2,}")
RESULT_RE = re.compile(
    r"^(?P<status>ok|changed|skipping|fatal|failed): "
    r"\[(?P<host>[^\]\s]+)(?: -> [^\]]*)?\]"
)
IGNORING_RE = re.compile(r"^\.\.\.ignoring\s*$")

_STATUS_RANK = {HOST_SKIPPED: 0, HOST_EXECUTED: 1, HOST_FAILED: 2}
_RESULT_STATUS = {
    "ok": HOST_EXECUTED,
    "changed": HOST_EXECUTED,
    "skipping": HOST_SKIPPED,
    "fatal": HOST_FAILED,
    "failed": HOST_FAILED,
}


def _role_time(line: str) -> tuple[str, float] | None:
    """Return (name, seconds) for a profile summary line, else None.

    The ``total`` line survives as the ``total`` row (recap sum, used to
    cross-check the parse); ``<role> : <task>`` profile_tasks entries are
    dropped.
    """
    match = LINE_RE.match(line)
    if not match:
        return None
    name = match.group("name").strip()
    if not name or " : " in name:
        return None
    if name.lower() == TOTAL_ROW:
        name = TOTAL_ROW
    try:
        return name, float(match.group("seconds"))
    except ValueError:
        return None


def _sorted(totals: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


class _HostStatus:
    """Per-(role, host) task outcome, escalating skipped < executed < failed.

    A ``...ignoring`` line right after a failure result downgrades that
    failure back to executed (ignore_errors semantics)."""

    def __init__(self) -> None:
        self.status: dict[str, dict[str, str]] = defaultdict(dict)
        self._last_failure: tuple[str, str] | None = None

    def record(self, role: str, host: str, status: str) -> None:
        current = self.status[role].get(host)
        if current is None or _STATUS_RANK[status] > _STATUS_RANK[current]:
            self.status[role][host] = status
        self._last_failure = (role, host) if status == HOST_FAILED else None

    def downgrade_ignored_failure(self) -> None:
        if self._last_failure is None:
            return
        role, host = self._last_failure
        if self.status[role].get(host) == HOST_FAILED:
            self.status[role][host] = HOST_EXECUTED
        self._last_failure = None

    def serialized(self, role: str) -> str:
        return " ".join(
            f"{host}={status}"
            for host, status in sorted(self.status.get(role, {}).items())
        )


def parse_log(log_path: str | Path) -> list[RoleRuntime]:
    """Ansible run log -> records.

    When the log carries the matrix-deploy round/pass markers, the result is
    segmented (one block of records per variant round + pass). Otherwise a
    single combined block is returned. Runtime rows are read from the
    ``ROLES RECAP`` sections only (never ``TASKS RECAP``, whose role-less
    task rows would double-count); a log without any recap header falls back
    to reading every profile-shaped line. The recap ``total`` line survives
    as the ``total`` row so consumers can cross-check the parsed sum.
    Per-host task results (``ok:``, ``changed:``, ``skipping:``, ``fatal:``,
    ``failed:`` under a ``TASK [role : ...]`` header) accumulate into each
    record's ``hosts`` field; delegation targets (``[host -> other]``) count
    for the source host. Raises FileNotFoundError when the log is absent
    (the caller turns that into a hard failure).
    """
    path = Path(log_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    text = path.read_text(
        encoding="utf-8", errors="replace"
    )  # nocheck: cache-read one-shot parse of a deploy log, no reuse to cache
    has_sections = "ROLES RECAP" in text

    segments: list[tuple[tuple[str, str, str, str], dict[str, float], _HostStatus]]
    segments = []
    current: dict[str, float] | None = None
    combined: dict[str, float] = defaultdict(float)
    combined_hosts = _HostStatus()
    current_hosts: _HostStatus | None = None
    current_role: str | None = None
    in_roles_recap = not has_sections
    for raw in text.splitlines():
        line = RUNNER_TS_RE.sub("", ANSI_RE.sub("", raw).rstrip())
        marker = SEGMENT_RE.search(line)
        if marker:
            meta = (
                marker.group("round"),
                marker.group("rounds"),
                marker.group("pass"),
                marker.group("mode"),
            )
            current = defaultdict(float)
            current_hosts = _HostStatus()
            segments.append((meta, current, current_hosts))
            current_role = None
            continue
        if has_sections:
            if ROLES_RECAP_RE.match(line):
                in_roles_recap = True
                continue
            if OTHER_RECAP_RE.match(line):
                in_roles_recap = False
                continue
        task = TASK_RE.search(line)
        if task:
            current_role = task.group("role").strip()
            continue
        if "TASK [" in line:
            current_role = None
            continue
        if IGNORING_RE.match(line):
            combined_hosts.downgrade_ignored_failure()
            if current_hosts is not None:
                current_hosts.downgrade_ignored_failure()
            continue
        result = RESULT_RE.match(line)
        if result and current_role:
            status = _RESULT_STATUS[result.group("status")]
            combined_hosts.record(current_role, result.group("host"), status)
            if current_hosts is not None:
                current_hosts.record(current_role, result.group("host"), status)
            continue
        if not in_roles_recap:
            continue
        row = _role_time(line)
        if not row:
            continue
        combined[row[0]] += row[1]
        if current is not None:
            current[row[0]] += row[1]

    records: list[RoleRuntime] = []
    for (rnd, rounds, pass_num, mode), totals, hosts in segments:
        for role, seconds in _sorted(totals):
            records.append(
                RoleRuntime(
                    role,
                    seconds,
                    rnd,
                    rounds,
                    pass_num,
                    mode,
                    hosts.serialized(role),
                )
            )
    if records:
        return records
    return [
        RoleRuntime(role, seconds, hosts=combined_hosts.serialized(role))
        for role, seconds in _sorted(combined)
    ]
