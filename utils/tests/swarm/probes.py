"""Read-only host probes the swarm-matrix watchdog prints around a spike.

They name what holds the runner's memory and what writes its disk, so a
runner lost to either leaves the culprit in the step log.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

CONTAINER_ID = re.compile(r"[0-9a-f]{64}")


def parse_write_bytes(text: str) -> dict[str, int]:
    """
    Args:
        text: ``grep -H write_bytes /proc/[0-9]*/io`` output.

    Returns:
        Per pid the bytes it has written so far.
    """
    found: dict[str, int] = {}
    for line in text.splitlines():
        path, _, value = line.partition(":write_bytes:")
        pid = path.removeprefix("/proc/").removesuffix("/io")
        if pid.isdigit() and value.strip().isdigit():
            found[pid] = int(value)
    return found


def top_writers(
    before: dict[str, int], after: dict[str, int], rows: int
) -> list[tuple[str, int]]:
    """
    Args:
        before: parse_write_bytes() of the first snapshot.
        after: parse_write_bytes() of the second snapshot.
        rows: how many writers to return.

    Returns:
        ``(pid, bytes written between the snapshots)``, largest first.
    """
    deltas = [(pid, written - before.get(pid, 0)) for pid, written in after.items()]
    return sorted((d for d in deltas if d[1] > 0), key=lambda d: -d[1])[:rows]


def _write_bytes() -> dict[str, int]:
    try:
        out = subprocess.run(
            ["sudo", "-n", "sh", "-c", "grep -H write_bytes /proc/[0-9]*/io"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return parse_write_bytes(out)


def _comm(pid: str) -> str:
    try:
        comm = Path(f"/proc/{pid}/comm")
        return comm.read_text(encoding="utf-8").strip()  # nocheck: cache-read  live pid
    except OSError:
        return "?"


def _top_rss(rows: int) -> list[str]:
    try:
        out = subprocess.run(
            ["ps", "-eo", "rss=,comm=", "--sort=-rss"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = []
    for line in out.splitlines()[:rows]:
        rss, _, command = line.strip().partition(" ")
        if rss.isdigit():
            lines.append(f"{int(rss) // 1024}M {command.strip()}")
    return lines


def _status_kb(text: str, key: str) -> int:
    for line in text.splitlines():
        name, _, value = line.partition(":")
        if name == key:
            amount = value.split()
            return int(amount[0]) if amount and amount[0].isdigit() else 0
    return 0


def memory_by_container(proc_root: Path, rows: int) -> list[str]:
    """Rank the runner's memory holders by container, swap included.

    A lab node's nested containers each count on their own: the innermost
    container id in a process's cgroup path names its group.

    Args:
        proc_root: the procfs mount, ``/proc`` on a live host.
        rows: how many groups to return.

    Returns:
        ``"<RSS + swap>M <largest process>(<container id or host>, <processes>)"``
        per group, heaviest first.
    """
    groups: dict[str, list] = {}
    for status in proc_root.glob("[0-9]*/status"):
        try:
            text = status.read_text(encoding="utf-8")  # nocheck: cache-read  live pid
            membership = status.parent / "cgroup"
            cgroup = membership.read_text("utf-8")  # nocheck: cache-read  live pid
        except OSError:
            continue
        kb = _status_kb(text, "VmRSS") + _status_kb(text, "VmSwap")
        if kb == 0:
            continue
        ids = CONTAINER_ID.findall(cgroup)
        key = ids[-1][:12] if ids else "host"
        entry = groups.setdefault(key, [0, 0, "?", 0])
        entry[0] += kb
        entry[1] += 1
        if kb > entry[3]:
            name = next(
                (
                    line.partition(":")[2].strip()
                    for line in text.splitlines()
                    if line.startswith("Name:")
                ),
                "?",
            )
            entry[2], entry[3] = name, kb
    ranked = sorted(groups.items(), key=lambda group: -group[1][0])[:rows]
    return [
        f"{total // 1024}M {name}({key}, {count})"
        for key, (total, count, name, _) in ranked
    ]


def zram_usage(sys_block: Path) -> list[str]:
    """
    Args:
        sys_block: the sysfs block directory, ``/sys/block`` on a live host.

    Returns:
        ``"<device> <swapped>M in <RAM used>M"`` per zram device, from the
        first and third ``mm_stat`` fields.
    """
    found = []
    for stat in sorted(sys_block.glob("zram*/mm_stat")):
        try:
            fields = stat.read_text("utf-8").split()  # nocheck: cache-read  live
        except OSError:
            continue
        if len(fields) >= 3 and fields[0].isdigit() and fields[2].isdigit():
            found.append(
                f"{stat.parent.name} {int(fields[0]) // 2**20}M in "
                f"{int(fields[2]) // 2**20}M"
            )
    return found


def memory_line(rows: int) -> str:
    """
    Args:
        rows: how many container groups the line names.

    Returns:
        The ``top memory`` banner of the live host, the zram devices first.
    """
    return (
        "=== swarm-matrix: top memory "
        + " | ".join(
            zram_usage(Path("/sys/block")) + memory_by_container(Path("/proc"), rows)
        )
        + " ==="
    )


def spike_report(rows: int, window_s: float) -> list[str]:
    """Name what eats the host while a spike is under way.

    Args:
        rows: how many processes or groups each line names.
        window_s: the interval the disk writers are measured over.

    Returns:
        The largest resident processes, the heaviest containers with their
        swap, and the processes that wrote the most bytes over the window.
    """
    before = _write_bytes()
    time.sleep(window_s)
    after = _write_bytes()
    writers = [
        f"{written // 2**20}M {_comm(pid)}({pid})"
        for pid, written in top_writers(before, after, rows)
    ]
    return [
        "=== swarm-matrix: top rss " + " | ".join(_top_rss(rows)) + " ===",
        memory_line(rows),
        "=== swarm-matrix: top writers/s " + " | ".join(writers) + " ===",
    ]
