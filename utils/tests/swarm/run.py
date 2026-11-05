from __future__ import annotations

import subprocess
import time

from utils.tests.swarm.watchdog import run_watched

__all__ = ["run_step", "run_watched", "top_processes"]

TOP_ROWS = 12


def top_processes(rows: int = TOP_ROWS) -> list[str]:
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
