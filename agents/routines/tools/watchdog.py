"""Hang watchdog: a deploy is hung when it has produced no output for longer
than its slowest healthy task may stay silent, and its process tree did no
work since the last poll; not when it has run for a long time.

Ansible prints nothing while a task runs, so the silence threshold is the
worst budget of the slowest task, an onion Playwright run: its run timeout plus
the onion reachability wait, both read from the Playwright role's vars, the
SPOT the role's own parallel budget is computed from.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from utils import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

PLAYWRIGHT_VARS = f"roles/test-e2e-playwright/{ROLE_FILE_VARS_MAIN}"
_PLAYWRIGHT_VARS = PROJECT_ROOT / PLAYWRIGHT_VARS
_PROC = Path("/proc")
_UTIME_STIME_AFTER_COMM = slice(11, 13)


def _playwright_budget(vars_file: Path) -> float:
    values = yaml.safe_load(vars_file.read_text(encoding="utf-8"))
    retries = int(values["TEST_E2E_PLAYWRIGHT_ONION_PROBE_RETRIES"])
    delay = int(values["TEST_E2E_PLAYWRIGHT_ONION_PROBE_DELAY"])
    max_time = int(values["TEST_E2E_PLAYWRIGHT_ONION_PROBE_MAX_TIME"])
    onion_wait = 2 * retries * (max_time + delay) + retries * delay
    return float(int(values["TEST_E2E_PLAYWRIGHT_ONION_RUN_TIMEOUT"]) + onion_wait)


SILENCE_SECONDS = _playwright_budget(_PLAYWRIGHT_VARS)


def is_hung(timestamps: list[float], now: float, silence: float) -> bool:
    """Return whether the run has been silent longer than ``silence`` seconds.

    The gap is measured from the most recent output timestamp to ``now``, never
    from the run's start, so total runtime does not enter the verdict. With no
    recorded output there is no silence baseline, so the run is not classified
    as hung.

    Args:
        timestamps: epoch seconds of each captured output line.
        now: the current epoch seconds.
        silence: the silence threshold in seconds, ``SILENCE_SECONDS`` for a
            deploy.
    """
    if not timestamps:
        return False
    return (now - max(timestamps)) > silence


def _children(pid: int) -> list[int]:
    found: list[int] = []
    for task in (_PROC / str(pid) / "task").glob("*"):
        children = task / "children"
        if children.is_file():
            found.extend(int(child) for child in children.read_text().split())
    return found


def process_ticks(pid: int) -> int | None:
    """Return the CPU clock ticks the process ``pid`` and every descendant
    used so far, or ``None`` when the process is gone: two polls with equal
    ticks show an idle tree, ``None`` a run that ended.

    Args:
        pid: the process id of the run's top command.
    """
    stat = _PROC / str(pid) / "stat"
    if not stat.is_file():
        return None
    fields = stat.read_text().rsplit(")", 1)[1].split()
    ticks = sum(int(value) for value in fields[_UTIME_STIME_AFTER_COMM])
    return ticks + sum(process_ticks(child) or 0 for child in _children(pid))
