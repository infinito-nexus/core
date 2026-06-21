"""Time-budget guard for the variant-deploy matrix (INFINITO_MAX_RUNTIME)."""

from __future__ import annotations

import os
import time

from utils.annotations.message import warning

_BUFFER_SECONDS = 30 * 60

_OVERFLOW_CUT = "cut"
_OVERFLOW_FAIL = "fail"
_OVERFLOW_MODES = (_OVERFLOW_CUT, _OVERFLOW_FAIL)


def _parse_overflow_mode(raw: str | None) -> str:
    mode = (raw or "").strip().lower() or _OVERFLOW_CUT
    if mode not in _OVERFLOW_MODES:
        raise SystemExit(
            f"INFINITO_VARIANT_TIME_OVERFLOW must be one of {_OVERFLOW_MODES}, "
            f"got {raw!r}"
        )
    return mode


def _parse_duration_seconds(raw: str | None) -> int | None:
    if not raw:
        return None
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

    INFINITO_VARIANT_TIME_OVERFLOW decides what happens when the remaining
    rounds no longer fit the budget: ``cut`` (default) warns via a CI
    annotation and skips the rest without failing; ``fail`` aborts the deploy
    with a non-zero exit so a runner that cannot complete its whole variant
    slice in time is treated as a hard failure rather than a silent cut."""

    def __init__(self) -> None:
        self.max_seconds = _parse_duration_seconds(
            os.environ.get("INFINITO_MAX_RUNTIME")
        )
        self.overflow_mode = _parse_overflow_mode(
            os.environ.get("INFINITO_VARIANT_TIME_OVERFLOW")
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
        detail = (
            f"after {done}/{total} round(s): elapsed {int(elapsed)}s + longest "
            f"round {int(self._longest_round)}s + {_BUFFER_SECONDS}s buffer "
            f"({int(projected)}s) would exceed INFINITO_MAX_RUNTIME "
            f"({self.max_seconds}s); {total - done} round(s) remaining"
        )
        if self.overflow_mode == _OVERFLOW_FAIL:
            raise SystemExit(
                f"Variant matrix budget exceeded {detail}. "
                "INFINITO_VARIANT_TIME_OVERFLOW=fail — failing the deploy "
                "instead of cutting the remaining rounds."
            )
        warning(
            f"Stopped the variant matrix {detail}. Skipped the remaining "
            "round(s) — not a failure (INFINITO_VARIANT_TIME_OVERFLOW=cut).",
            title="Deploy runtime budget",
        )
        return True

    def start_round(self) -> None:
        self._round_start = time.monotonic()

    def end_round(self) -> None:
        self._longest_round = max(
            self._longest_round, time.monotonic() - self._round_start
        )
