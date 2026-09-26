"""Run one swarm-matrix step, aborting before the runner's disk or RAM fills.

The Actions Worker dies silently on ENOSPC while writing its own logs, so a
full disk truncates the job without diagnostics. Terminating the step at
DISK_FLOOR_MB keeps enough room for the rescue artifacts and the log upload.
"""

from __future__ import annotations

import shutil
import subprocess
import time

from utils import PROJECT_ROOT
from utils.env.runtime import mem_available_mb, mem_stall_pct, mem_total_mb

DISK_FLOOR_MB = 6 * 2**10
MEM_FLOOR_RATIO = 0.06


def _abort(proc: subprocess.Popen[bytes], banner: str, probe: list[str]) -> int:
    print(banner, flush=True)
    subprocess.run(probe, check=False)
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return 75


def run_step(cmd: list[str], *, env: dict[str, str], label: str) -> int:
    """Announce a matrix step, run it, and report what it cost.

    Args:
        cmd: argv of the step.
        env: environment the step runs with.
        label: phase name for the banners.

    Returns:
        The step's exit code.
    """
    print(f"=== swarm-matrix: {label} ===", flush=True)
    started = time.monotonic()
    rc = run_watched(cmd, env=env)
    print(
        f"=== swarm-matrix: {label} took {time.monotonic() - started:.0f}s (rc={rc}) ===",
        flush=True,
    )
    return rc


def run_watched(cmd: list[str], *, env: dict[str, str]) -> int:
    """Run a step, aborting visibly before the runner disk or RAM fills.

    Args:
        cmd: argv of the step.
        env: environment the step runs with.

    Returns:
        The step's exit code, or the abort code when a floor was hit.
    """
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env)
    while True:
        try:
            return int(proc.wait(timeout=30))
        except subprocess.TimeoutExpired:
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
            stall = mem_stall_pct()
            print(
                f"=== swarm-matrix: host mem {avail}M/{total}M available, "
                f"disk {free_mb}M free on /, stall60 {stall:.1f}% ===",
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
