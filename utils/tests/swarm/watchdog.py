"""Host-health watchdog around a swarm-matrix step.

A hosted runner that fills its disk, exhausts its RAM or wedges on a stuck
mount dies without a trace: the Actions Worker stops, the deploy step stays
``in_progress`` and every diagnostic upload after it stays ``pending``, so no
artifact survives. The watchdog samples the host while the step runs and ends
the step itself once a floor is crossed, which turns a silent job loss into a
failed step the post-mortem and upload steps still get to run after.

The sample line is the in-band half of that: it carries memory, disk and the
three PSI resources plus the uninterruptible-process count, so a cut that
happens anyway can still be attributed afterwards from the step log alone.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.env.runtime import (
    cpu_stall_pct,
    io_stall_pct,
    mem_available_mb,
    mem_stall_pct,
    mem_total_mb,
    uninterruptible_switches,
)
from utils.tests.swarm.probes import (
    memory_line,
    network_line,
    network_report,
    oom_kills,
    oom_victims,
    protect_from_oom,
    reachable,
    runner_pids,
    spike_report,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

DISK_FLOOR_MB = 6 * 2**10
STORAGE_ROOTS = ("/", "/var/lib/containerd")
MEM_FLOOR_RATIO = 0.06
IO_STALL_CEILING_PCT = 50.0
SAMPLE_INTERVAL_S = 10
TOP_ROWS = 12
TOP_EVERY_SAMPLES = 60
STALL_WINDOW_S = 60
HUNG_TASK_S = 30
WEDGE_SAMPLES = 2
FAST_INTERVAL_S = 1
SPIKE_MB = 2**10
SPIKE_COOLDOWN_S = 30
FLOOR_ETA_S = 5
OOM_LINES = 4
PROC_ROOT = Path("/proc")
NET_PROBE_HOST = "github.com"
NET_PROBE_PORT = 443
NET_PROBE_EVERY_S = 15
NET_PROBE_TIMEOUT_S = 5.0
NET_LOST_PROBES = 4
ABORT_RC = 75
_FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def _signal_step(proc: subprocess.Popen[bytes], sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, sig)


@contextlib.contextmanager
def _forwarding(proc: subprocess.Popen[bytes]) -> Iterator[None]:
    previous = {
        sig: signal.signal(sig, lambda signum, _frame: _signal_step(proc, signum))
        for sig in _FORWARDED_SIGNALS
    }
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _abort(proc: subprocess.Popen[bytes], banner: str, probe: list[str]) -> int:
    print(banner, flush=True)
    subprocess.run(probe, check=False)
    _signal_step(proc, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=30)
    _signal_step(proc, signal.SIGKILL)
    proc.wait()
    return ABORT_RC


def lowest_free_mb() -> tuple[int, str]:
    """Measure the storage root closest to running full.

    Returns:
        Free MB on the fullest existing root in STORAGE_ROOTS, and that root.
    """
    return min(
        (shutil.disk_usage(root).free // 2**20, root)
        for root in STORAGE_ROOTS
        if Path(root).is_dir()
    )


def blocked_streaks(
    previous: dict[str, tuple[int, int]], switches: dict[str, int]
) -> dict[str, tuple[int, int]]:
    """
    Args:
        previous: blocked_streaks() of the previous sample.
        switches: uninterruptible_switches() of this sample.

    Returns:
        Per `D`-state pid its context switches and the number of samples in a
        row it has stayed in `D` without a single one.
    """
    streaks: dict[str, tuple[int, int]] = {}
    for pid, count in switches.items():
        seen, streak = previous.get(pid, (-1, -1))
        streaks[pid] = (count, streak + 1 if seen == count else 0)
    return streaks


def hung_tasks(streaks: dict[str, tuple[int, int]]) -> int:
    """
    Args:
        streaks: blocked_streaks() of this sample.

    Returns:
        The number of tasks blocked in `D` without a context switch for at
        least HUNG_TASK_S.
    """
    return sum(
        1 for _, streak in streaks.values() if streak * SAMPLE_INTERVAL_S >= HUNG_TASK_S
    )


def sample_line(
    *,
    avail: int,
    total: int,
    free_mb: int,
    root: str,
    mem_stall: float,
    io_stall: float,
    cpu_stall: float,
    dstate: int,
    hung: int,
) -> str:
    """Render one host-health sample for the step log.

    Args:
        avail: MemAvailable in MB.
        total: MemTotal in MB.
        free_mb: free space on root in MB.
        root: the storage root closest to running full.
        mem_stall: `full avg60` memory pressure in percent.
        io_stall: `full avg60` I/O pressure in percent.
        cpu_stall: `some avg60` CPU pressure in percent.
        dstate: number of processes in uninterruptible state.
        hung: how many of them sat in D without a context switch for at
            least HUNG_TASK_S.

    Returns:
        The banner line, carrying the three resources a lost runner can be
        attributed to plus the D-state count that separates a wedged mount
        from plain contention.
    """
    return (
        f"=== swarm-matrix: host mem {avail}M/{total}M available, "
        f"disk {free_mb}M free on {root}, stall60 {mem_stall:.1f}%, "
        f"io60 {io_stall:.1f}%, cpu60 {cpu_stall:.1f}%, dstate {dstate}, "
        f"hung {hung} ==="
    )


def spike_kind(
    previous: tuple[int, int], current: tuple[int, int]
) -> tuple[int, int] | None:
    """
    Args:
        previous: ``(free disk MB, available memory MB)`` of the last sample.
        current: the same pair FAST_INTERVAL_S later.

    Returns:
        ``(disk drop MB, memory drop MB)`` when either reached SPIKE_MB,
        else ``None``.
    """
    disk_drop = previous[0] - current[0]
    mem_drop = previous[1] - current[1]
    if disk_drop >= SPIKE_MB or mem_drop >= SPIKE_MB:
        return disk_drop, mem_drop
    return None


def floor_within_eta(free_mb: int, disk_drop_mb: int) -> bool:
    """
    Args:
        free_mb: free MB on the fullest storage root now.
        disk_drop_mb: MB that root lost over the last FAST_INTERVAL_S.

    Returns:
        Whether that rate reaches DISK_FLOOR_MB within FLOOR_ETA_S.
    """
    return disk_drop_mb > 0 and free_mb - DISK_FLOOR_MB <= disk_drop_mb * FLOOR_ETA_S


def _tripwire(
    proc: subprocess.Popen[bytes], stop: threading.Event, tripped: threading.Event
) -> None:
    previous: tuple[int, int] | None = None
    reported = -float(SPIKE_COOLDOWN_S)
    kills = oom_kills(PROC_ROOT)
    while not stop.wait(FAST_INTERVAL_S):
        counted = oom_kills(PROC_ROOT)
        if kills is not None and counted is not None and counted > kills:
            print(
                f"=== swarm-matrix: OOM KILL x{counted - kills} "
                f"({counted} since boot) ===",
                flush=True,
            )
            for line in oom_victims(OOM_LINES):
                print(f"=== swarm-matrix: kernel: {line} ===", flush=True)
            print(memory_line(TOP_ROWS), flush=True)
        if counted is not None:
            kills = counted
        free_mb, root = lowest_free_mb()
        current = (free_mb, mem_available_mb())
        drop = spike_kind(previous, current) if previous else None
        previous = current
        if drop is None:
            continue
        now = time.monotonic()
        if now - reported >= SPIKE_COOLDOWN_S:
            reported = now
            print(
                f"=== swarm-matrix: SPIKE disk -{drop[0]}M ({free_mb}M free on "
                f"{root}), mem -{drop[1]}M ({current[1]}M available) in "
                f"{FAST_INTERVAL_S}s ===",
                flush=True,
            )
            for line in spike_report(TOP_ROWS, FAST_INTERVAL_S):
                print(line, flush=True)
        if floor_within_eta(free_mb, drop[0]):
            tripped.set()
            _abort(
                proc,
                f"=== swarm-matrix: DISK EXHAUSTION IMMINENT ({free_mb}M free on "
                f"{root}, -{drop[0]}M in {FAST_INTERVAL_S}s) - aborting step ===",
                ["df", "-h", *STORAGE_ROOTS],
            )
            return


def _netwire(
    proc: subprocess.Popen[bytes], stop: threading.Event, tripped: threading.Event
) -> None:
    failures = 0
    while not stop.wait(NET_PROBE_EVERY_S):
        if reachable(NET_PROBE_HOST, NET_PROBE_PORT, NET_PROBE_TIMEOUT_S):
            failures = 0
            continue
        failures += 1
        print(
            f"=== swarm-matrix: {NET_PROBE_HOST}:{NET_PROBE_PORT} unreachable "
            f"({failures}/{NET_LOST_PROBES}) ===",
            flush=True,
        )
        if failures < NET_LOST_PROBES:
            continue
        for line in network_report(PROC_ROOT):
            print(line, flush=True)
        print(memory_line(TOP_ROWS), flush=True)
        tripped.set()
        _abort(
            proc,
            f"=== swarm-matrix: NETWORK LOST ({NET_PROBE_HOST}:{NET_PROBE_PORT} "
            f"unreachable for {failures * NET_PROBE_EVERY_S}s) - aborting step ===",
            ["ip", "-brief", "addr"],
        )
        return


def run_watched(cmd: list[str], *, env: dict[str, str]) -> int:
    """Run a step, aborting visibly before the runner disk, RAM or I/O wedges.

    The Actions Worker dies silently on ENOSPC while writing its own logs, so
    a full disk truncates the job without diagnostics; terminating the step at
    DISK_FLOOR_MB keeps enough room for rescue artifacts and the log upload.
    A stuck mount produces the same silence without touching either floor, so
    IO_STALL_CEILING_PCT ends the step while the runner can still upload. It
    takes three things together, because the pressure reading alone cannot
    tell a wedge from a busy disk and is not even this step's: a task in D
    state on the same sample, WEDGE_SAMPLES breaches in a row, and a step old
    enough to own a whole STALL_WINDOW_S of the trailing average. Without the
    last one an I/O-heavy predecessor aborts its successor before that step
    has issued a single read. A side thread samples every FAST_INTERVAL_S,
    because a runner that went from a healthy sample to silence within one
    SAMPLE_INTERVAL_S left nothing to attribute the loss to: it names the
    largest and the busiest-writing processes of a spike, and ends the step
    when the disk would reach DISK_FLOOR_MB before the next slow sample. On a
    hosted runner a second thread probes GitHub: a runner that keeps its RAM
    and disk but loses its network is declared lost hours later with no log
    tail, so NET_LOST_PROBES failures in a row print the network state and end
    the step, and the teardown that follows can give the network back.

    Args:
        cmd: argv of the step.
        env: environment the step runs with.

    Returns:
        The step's exit code, or ABORT_RC when a floor was hit.
    """
    protected = protect_from_oom(runner_pids(PROC_ROOT))
    print(
        "=== swarm-matrix: runner agent exempt from the OOM killer: "
        f"{', '.join(protected) or 'none'} ===",
        flush=True,
    )
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env, process_group=0)
    stop = threading.Event()
    tripped = threading.Event()
    wires = [
        threading.Thread(target=_tripwire, args=(proc, stop, tripped), daemon=True)
    ]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        wires.append(
            threading.Thread(target=_netwire, args=(proc, stop, tripped), daemon=True)
        )
    with _forwarding(proc):
        for wire in wires:
            wire.start()
        try:
            returned = _watch(proc)
        finally:
            stop.set()
            for wire in wires:
                wire.join()
    return ABORT_RC if tripped.is_set() else returned


def top_processes(rows: int) -> list[str]:
    """Return the busiest processes of the runner over a 3 s window.

    The lab nodes are containers on the runner's kernel, so this sees every
    nested container process too. The first ``top`` frame averages over each
    process's lifetime; only the second frame covers the window.

    Args:
        rows: how many process lines to return.

    Returns:
        ``"<%CPU> <command>"`` lines, busiest first; empty when ``top`` fails.
    """
    try:
        out = subprocess.run(
            ["top", "-b", "-n", "2", "-d", "3", "-o", "%CPU", "-w", "200"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    frame = out.rsplit("\n\n", 2)[-1].splitlines()
    header = next((i for i, line in enumerate(frame) if "%CPU" in line), None)
    if header is None:
        return []
    columns = frame[header].split()
    cpu, command = columns.index("%CPU"), columns.index("COMMAND")
    lines = []
    for line in frame[header + 1 :]:
        fields = line.split(None, command)
        if len(fields) > command:
            lines.append(f"{fields[cpu]} {fields[command]}")
        if len(lines) == rows:
            break
    return lines


def _watch(proc: subprocess.Popen[bytes]) -> int:
    samples = 0
    wedged = 0
    streaks: dict[str, tuple[int, int]] = {}
    while True:
        try:
            return int(proc.wait(timeout=SAMPLE_INTERVAL_S))
        except subprocess.TimeoutExpired:
            samples += 1
            free_mb, root = lowest_free_mb()
            if free_mb < DISK_FLOOR_MB:
                return _abort(
                    proc,
                    "=== swarm-matrix: DISK EXHAUSTION IMMINENT "
                    f"(<{DISK_FLOOR_MB}M free on {root}) - aborting step ===",
                    ["df", "-h", *STORAGE_ROOTS],
                )
            avail = mem_available_mb()
            total = mem_total_mb()
            io_stall = io_stall_pct()
            streaks = blocked_streaks(streaks, uninterruptible_switches())
            dstate = len(streaks)
            hung = hung_tasks(streaks)
            print(
                sample_line(
                    avail=avail,
                    total=total,
                    free_mb=free_mb,
                    root=root,
                    mem_stall=mem_stall_pct(),
                    io_stall=io_stall,
                    cpu_stall=cpu_stall_pct(),
                    dstate=dstate,
                    hung=hung,
                ),
                flush=True,
            )
            if samples % TOP_EVERY_SAMPLES == 0:
                print(
                    "=== swarm-matrix: top cpu "
                    + " | ".join(top_processes(TOP_ROWS))
                    + " ===",
                    flush=True,
                )
                print(memory_line(TOP_ROWS), flush=True)
                print(network_line(PROC_ROOT), flush=True)
            if total and avail < total * MEM_FLOOR_RATIO:
                print(memory_line(TOP_ROWS), flush=True)
                return _abort(
                    proc,
                    "=== swarm-matrix: MEMORY EXHAUSTION IMMINENT "
                    f"({avail}M available, below {MEM_FLOOR_RATIO:.0%} of RAM)"
                    " - aborting step ===",
                    ["free", "-m"],
                )
            owns_window = samples * SAMPLE_INTERVAL_S >= STALL_WINDOW_S
            breached = io_stall >= IO_STALL_CEILING_PCT and hung > 0
            wedged = wedged + 1 if owns_window and breached else 0
            if wedged >= WEDGE_SAMPLES:
                return _abort(
                    proc,
                    "=== swarm-matrix: I/O WEDGE "
                    f"({io_stall:.1f}% full stall60 with {dstate} task(s) in D "
                    f"state, {hung} hung for {HUNG_TASK_S}s+, {wedged} samples "
                    f"at or above {IO_STALL_CEILING_PCT:.0f}%) - aborting step ===",
                    ["cat", "/proc/pressure/io"],
                )
