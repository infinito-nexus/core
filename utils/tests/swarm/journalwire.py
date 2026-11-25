"""Stream the runner's own journal into the step log while a swarm step runs.

A hosted runner that dies within one watchdog sample leaves a healthy last
sample and nothing else: RAM, disk and pressure all look fine and the cause
never reaches the log. The runner's journal sees what those samples cannot,
because it carries the kernel ring buffer and every host unit that stops,
fails or gets killed. Streaming it at priority notice and above puts the last
seconds before such a death into the log while the network can still carry it.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

JOURNAL_CMD = (
    "sudo",
    "-n",
    "journalctl",
    "--follow",
    "--lines=0",
    "--no-pager",
    "--output=short-iso",
    "--priority=notice",
)
JOURNAL_BURST = 40
JOURNAL_WINDOW_S = 10.0


def journal_line(line: str) -> str:
    """
    Args:
        line: one journal record as journalctl prints it.

    Returns:
        The record framed like every other watchdog line.
    """
    return f"=== swarm-matrix: journal: {line.rstrip()} ==="


def throttle(
    lines: Iterable[str],
    emit: Callable[[str], None],
    clock: Callable[[], float],
    *,
    burst: int,
    window_s: float,
) -> None:
    """Emit journal records, at most ``burst`` per ``window_s``.

    A flapping unit can write thousands of records a minute; the step log must
    stay readable, so the surplus of a window is counted instead of printed and
    reported once the next record opens a fresh window.

    Args:
        lines: journal records in arrival order.
        emit: sink for each rendered line.
        clock: monotonic seconds.
        burst: records printed per window.
        window_s: window length in seconds.
    """
    opened = clock()
    printed = 0
    dropped = 0
    for line in lines:
        now = clock()
        if now - opened >= window_s:
            if dropped:
                emit(f"=== swarm-matrix: journal: {dropped} record(s) suppressed ===")
            opened, printed, dropped = now, 0, 0
        if printed < burst:
            emit(journal_line(line))
            printed += 1
        else:
            dropped += 1


def journalwire(stop: threading.Event) -> None:
    """Follow the runner journal until ``stop`` is set.

    Args:
        stop: set by the watchdog when the step ends.
    """
    try:
        proc = subprocess.Popen(
            JOURNAL_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
        )
    except OSError as exc:
        print(f"=== swarm-matrix: journal stream unavailable: {exc} ===", flush=True)
        return

    def _reap() -> None:
        stop.wait()
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()

    threading.Thread(target=_reap, daemon=True).start()
    if proc.stdout is not None:
        throttle(
            proc.stdout,
            lambda text: print(text, flush=True),
            time.monotonic,
            burst=JOURNAL_BURST,
            window_s=JOURNAL_WINDOW_S,
        )
    proc.wait()
