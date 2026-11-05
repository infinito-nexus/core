"""Host command runners of the Swarm adapter; tests patch these."""

from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable

POLL_S = 2.0


def execute(
    argv: list[str], *, stdin: str | None = None, timeout: int = 120
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, input=stdin, capture_output=True, text=True, check=False, timeout=timeout
    )


def run(
    argv: list[str], *, stdin: str | None = None, check: bool = True, timeout: int = 120
) -> str:
    proc = execute(argv, stdin=stdin, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"{' '.join(argv[:6])} ...: rc={proc.returncode} {proc.stderr.strip()}"
        )
    return proc.stdout


def stream(argv: list[str], *, env: dict[str, str], timeout: int) -> int:
    return subprocess.run(
        argv, cwd=str(PROJECT_ROOT), env=env, check=False, timeout=timeout
    ).returncode


def wait_until(
    predicate: Callable[[], bool], *, timeout_s: float, interval_s: float = POLL_S
) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if predicate():
                return True
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)
