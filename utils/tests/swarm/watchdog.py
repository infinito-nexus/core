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

import shutil
import subprocess

from utils import PROJECT_ROOT
from utils.env.runtime import (
    cpu_stall_pct,
    io_stall_pct,
    mem_available_mb,
    mem_stall_pct,
    mem_total_mb,
    uninterruptible_procs,
)

DISK_FLOOR_MB = 6 * 2**10
MEM_FLOOR_RATIO = 0.06
IO_STALL_CEILING_PCT = 50.0
SAMPLE_INTERVAL_S = 10
STALL_WINDOW_S = 60
WEDGE_SAMPLES = 2
ABORT_RC = 75


def _abort(proc: subprocess.Popen[bytes], banner: str, probe: list[str]) -> int:
    print(banner, flush=True)
    subprocess.run(probe, check=False)
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return ABORT_RC


def sample_line(
    *,
    avail: int,
    total: int,
    free_mb: int,
    mem_stall: float,
    io_stall: float,
    cpu_stall: float,
    dstate: int,
) -> str:
    """Render one host-health sample for the step log.

    Args:
        avail: MemAvailable in MB.
        total: MemTotal in MB.
        free_mb: free space on / in MB.
        mem_stall: `full avg60` memory pressure in percent.
        io_stall: `full avg60` I/O pressure in percent.
        cpu_stall: `some avg60` CPU pressure in percent.
        dstate: number of processes in uninterruptible state.

    Returns:
        The banner line, carrying the three resources a lost runner can be
        attributed to plus the D-state count that separates a wedged mount
        from plain contention.
    """
    return (
        f"=== swarm-matrix: host mem {avail}M/{total}M available, "
        f"disk {free_mb}M free on /, stall60 {mem_stall:.1f}%, "
        f"io60 {io_stall:.1f}%, cpu60 {cpu_stall:.1f}%, dstate {dstate} ==="
    )


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
    has issued a single read.

    Args:
        cmd: argv of the step.
        env: environment the step runs with.

    Returns:
        The step's exit code, or ABORT_RC when a floor was hit.
    """
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env)
    samples = 0
    wedged = 0
    while True:
        try:
            return int(proc.wait(timeout=SAMPLE_INTERVAL_S))
        except subprocess.TimeoutExpired:
            samples += 1
            free_mb = shutil.disk_usage("/").free // 2**20
            if free_mb < DISK_FLOOR_MB:
                return _abort(
                    proc,
                    "=== swarm-matrix: DISK EXHAUSTION IMMINENT "
                    f"(<{DISK_FLOOR_MB}M free on /) - aborting step ===",
                    ["df", "-h", "/"],
                )
            avail = mem_available_mb()
            total = mem_total_mb()
            io_stall = io_stall_pct()
            dstate = uninterruptible_procs()
            print(
                sample_line(
                    avail=avail,
                    total=total,
                    free_mb=free_mb,
                    mem_stall=mem_stall_pct(),
                    io_stall=io_stall,
                    cpu_stall=cpu_stall_pct(),
                    dstate=dstate,
                ),
                flush=True,
            )
            if total and avail < total * MEM_FLOOR_RATIO:
                return _abort(
                    proc,
                    "=== swarm-matrix: MEMORY EXHAUSTION IMMINENT "
                    f"({avail}M available, below {MEM_FLOOR_RATIO:.0%} of RAM)"
                    " - aborting step ===",
                    ["free", "-m"],
                )
            owns_window = samples * SAMPLE_INTERVAL_S >= STALL_WINDOW_S
            breached = io_stall >= IO_STALL_CEILING_PCT and dstate > 0
            wedged = wedged + 1 if owns_window and breached else 0
            if wedged >= WEDGE_SAMPLES:
                return _abort(
                    proc,
                    "=== swarm-matrix: I/O WEDGE "
                    f"({io_stall:.1f}% full stall60 with {dstate} task(s) in D "
                    f"state, {wedged} samples at or above "
                    f"{IO_STALL_CEILING_PCT:.0f}%) - aborting step ===",
                    ["cat", "/proc/pressure/io"],
                )
