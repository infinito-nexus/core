"""The load figures the scheduler tick reads, parsed from what the host prints.

The host's CPU comes from two ``/proc/stat`` reads one tick apart and its GPU
from ``nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits``.
The translation lane's own share comes from its container: the CPU from one
``docker stats --no-stream --format '{{json .}}'`` line, the GPU from the
``nvidia-smi pmon -c 1 -s u`` rows of the processes ``docker top <container>
-eo pid`` lists. ``lane_sample`` folds them into the ``(host, lane)`` pair
``load.conditions`` judges, so the lane's own load never pauses it.
"""

from __future__ import annotations

import json

from utils.orchestrator.load import Load

_STAT_FIELDS = 8
_IDLE, _IOWAIT = 3, 4
_PMON_PID, _PMON_SM = 1, 3


def _cpu_times(stat: str) -> tuple[int, int]:
    line = next(row for row in stat.splitlines() if row.startswith("cpu "))
    values = [int(value) for value in line.split()[1 : _STAT_FIELDS + 1]]
    return sum(values), values[_IDLE] + values[_IOWAIT]


def cpu_percent(before: str, after: str) -> float:
    """Return the host's CPU use between two ``/proc/stat`` reads, in percent
    of its whole capacity; ``0`` when no time passed.

    Args:
        before: the earlier ``/proc/stat`` text.
        after: the later ``/proc/stat`` text.
    """
    total_before, idle_before = _cpu_times(before)
    total_after, idle_after = _cpu_times(after)
    elapsed = total_after - total_before
    if elapsed <= 0:
        return 0.0
    return 100.0 * (elapsed - (idle_after - idle_before)) / elapsed


def gpu_percent(query: str) -> float:
    """Return the host's mean GPU use over every GPU, in percent.

    Args:
        query: the ``nvidia-smi --query-gpu=utilization.gpu`` CSV, one GPU
            per line, without header and units.
    """
    values = [float(line) for line in query.splitlines() if line.strip()]
    return sum(values) / len(values) if values else 0.0


def lane_cpu(stats: str, container: str, cpus: int) -> float:
    """Return the lane container's CPU use as a share of the host's whole
    capacity, in percent; ``0`` when the container is not running.

    Args:
        stats: the ``docker stats --no-stream --format '{{json .}}'`` lines.
        container: the lane container's name.
        cpus: the host's CPU count; ``docker stats`` counts each CPU as 100 %.
    """
    for line in stats.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["Name"] == container:
            return float(row["CPUPerc"].rstrip("%")) / cpus
    return 0.0


def pids(top: str) -> frozenset[int]:
    """Return the process ids ``docker top <container> -eo pid`` lists.

    Args:
        top: its output, a ``PID`` header and one id per line.
    """
    return frozenset(int(line) for line in top.split() if line.isdigit())


def lane_gpu(pmon: str, lane_pids: frozenset[int], gpus: int) -> float:
    """Return the lane's GPU use as a share of every GPU, in percent.

    Args:
        pmon: the ``nvidia-smi pmon -c 1 -s u`` rows; ``-`` counts as 0.
        lane_pids: the lane container's process ids.
        gpus: the host's GPU count.
    """
    used = 0.0
    for line in pmon.splitlines():
        fields = line.split()
        if len(fields) <= _PMON_SM or line.lstrip().startswith("#"):
            continue
        sm = fields[_PMON_SM]
        if int(fields[_PMON_PID]) in lane_pids and sm != "-":
            used += float(sm)
    return used / gpus if gpus else 0.0


def lane_sample(
    *,
    stat_before: str,
    stat_after: str,
    gpu_query: str,
    stats: str,
    container: str,
    cpus: int,
    pmon: str,
    top: str,
) -> tuple[Load, Load]:
    """Return the ``(host, lane)`` pair of one tick.

    Args:
        stat_before: the ``/proc/stat`` text of the previous tick.
        stat_after: the ``/proc/stat`` text of this tick.
        gpu_query: the ``nvidia-smi`` utilization CSV; ``""`` without a GPU.
        stats: the ``docker stats`` JSON lines.
        container: the lane container's name.
        cpus: the host's CPU count.
        pmon: the ``nvidia-smi pmon`` rows; ``""`` without a GPU.
        top: the ``docker top <container> -eo pid`` output.
    """
    gpus = len([line for line in gpu_query.splitlines() if line.strip()])
    host = Load(cpu_percent(stat_before, stat_after), gpu_percent(gpu_query))
    lane = Load(lane_cpu(stats, container, cpus), lane_gpu(pmon, pids(top), gpus))
    return host, lane
