"""Time-budget guard for the variant-deploy matrix (INFINITO_MAX_RUNTIME)."""

from __future__ import annotations

import os
import time

from utils.annotations.message import warning

_BUFFER_SECONDS = 30 * 60


def _parse_duration_seconds(raw: str) -> int | None:
    raw = raw.strip().lower()
    if not raw:
        return None
    try:
        if raw.endswith("h"):
            return int(float(raw[:-1]) * 3600)
        if raw.endswith("m"):
            return int(float(raw[:-1]) * 60)
        if raw.endswith("s"):
            return int(float(raw[:-1]))
        return int(float(raw))
    except ValueError:
        return None


class RuntimeBudget:
    """Stops the variant matrix before INFINITO_MAX_RUNTIME is exceeded by
    projecting the next round from the longest round so far plus a buffer.
    Warns (CI annotation) on early stop; never fails the deploy."""

    def __init__(self) -> None:
        self.max_seconds = _parse_duration_seconds(
            os.environ.get("INFINITO_MAX_RUNTIME", "")
        )
        self._start = time.monotonic()
        self._longest_round = 0.0
        self._round_start = 0.0

    def exhausted(self, done: int, total: int) -> bool:
        if done == 0 or self.max_seconds is None:
            return False
        elapsed = time.monotonic() - self._start
        projected = elapsed + self._longest_round + _BUFFER_SECONDS
        if projected <= self.max_seconds:
            return False
        warning(
            f"Stopped the variant matrix after {done}/{total} round(s): elapsed "
            f"{int(elapsed)}s + longest round {int(self._longest_round)}s + "
            f"{_BUFFER_SECONDS}s buffer ({int(projected)}s) would exceed "
            f"INFINITO_MAX_RUNTIME ({self.max_seconds}s). Skipped {total - done} "
            "remaining round(s) — not a failure.",
            title="Deploy runtime budget",
        )
        return True

    def start_round(self) -> None:
        self._round_start = time.monotonic()

    def end_round(self) -> None:
        self._longest_round = max(
            self._longest_round, time.monotonic() - self._round_start
        )
