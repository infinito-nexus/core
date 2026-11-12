from __future__ import annotations

from pathlib import Path

import yaml

from utils import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

PLAYWRIGHT_VARS = f"roles/test-e2e-playwright/{ROLE_FILE_VARS_MAIN}"
_PLAYWRIGHT_VARS = PROJECT_ROOT / PLAYWRIGHT_VARS
BUSY_CORES = 1.0
CGROUP_MOUNT = Path("/sys/fs/cgroup")
CONTAINER_SCOPES = "docker-*.scope"
_USEC_PER_SECOND = 1_000_000
_CPU_STAT = "cpu.stat"
_USAGE_USEC = "usage_usec"
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


def _usage_usec(cgroup: Path) -> int:
    for line in (cgroup / _CPU_STAT).read_text().splitlines():
        key, _, value = line.partition(" ")
        if key == _USAGE_USEC:
            return int(value)
    raise ValueError(f"{cgroup / _CPU_STAT} holds no {_USAGE_USEC}")


def cgroup_usec(root: Path, mount: Path) -> int | None:
    """Return the CPU microseconds a stack container's cgroup used so far.

    Args:
        root: the cgroup directory of one stack container, for example
            ``/sys/fs/cgroup/system.slice/docker-<id>.scope``.
        mount: the cgroup v2 mount ``root`` lies under, ``CGROUP_MOUNT``.

    Returns:
        ``None`` when ``root`` is gone; else the usage of ``root``, which
        holds its nested cgroups, plus the usage of ``mount / <path below
        root>`` for every nested ``CONTAINER_SCOPES`` directory whose twin
        exists outside ``root``.
    """
    if not (root / _CPU_STAT).is_file():
        return None
    total = _usage_usec(root)
    for nested in root.rglob(CONTAINER_SCOPES):
        twin = mount / nested.relative_to(root)
        if (twin / _CPU_STAT).is_file() and not twin.is_relative_to(root):
            total += _usage_usec(twin)
    return total


def stack_usage(roots: list[str], mount: Path) -> list[int] | None:
    """Return the CPU microseconds each stack cgroup used so far.

    Args:
        roots: the cgroup directory of each container of the stack.
        mount: the cgroup v2 mount, ``CGROUP_MOUNT``.

    Returns:
        One ``cgroup_usec`` per entry of ``roots``, in their order; ``None``
        when one of them is gone.
    """
    usage = [cgroup_usec(Path(root), mount) for root in roots]
    if any(value is None for value in usage):
        return None
    return [value for value in usage if value is not None]


def stack_busy(
    usage: list[int] | None, last: list[int] | None, seconds: float | None
) -> bool:
    """Return whether one stack cgroup worked at least ``BUSY_CORES`` since
    the poll before.

    Args:
        usage: ``stack_usage`` at this poll, ``None`` when the run names no
            stack cgroup.
        last: ``stack_usage`` at the poll before, ``None`` at the first poll.
        seconds: the time from the poll before to this one, ``None`` at the
            first poll.

    Returns:
        ``False`` without ``usage``; ``True`` without a baseline of the same
        cgroups; else whether the usage of one cgroup grew by at least
        ``BUSY_CORES`` times ``seconds`` of CPU, each cgroup on its own.
    """
    if usage is None:
        return False
    if last is None or seconds is None or len(last) != len(usage):
        return True
    budget = BUSY_CORES * seconds * _USEC_PER_SECOND
    return any(now - before >= budget for now, before in zip(usage, last, strict=True))
