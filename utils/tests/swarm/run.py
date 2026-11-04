from __future__ import annotations

import time

from utils.tests.swarm.watchdog import run_watched

__all__ = ["run_step", "run_watched"]


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
