"""Hang watchdog: a deploy is hung when it has produced no output for too long,
not when it has run for a long time. The verdict is read from the gap between
the most recent output timestamp and now, so a long build that keeps writing is
never flagged while a silent one is.
"""

from __future__ import annotations


def is_hung(timestamps: list[float], now: float, silence: float = 900.0) -> bool:
    """Return whether the run has been silent longer than ``silence`` seconds.

    The gap is measured from the most recent output timestamp to ``now``, never
    from the run's start, so total runtime does not enter the verdict. With no
    recorded output there is no silence baseline, so the run is not classified
    as hung.

    Args:
        timestamps: epoch seconds of each captured output line.
        now: the current epoch seconds.
        silence: the silence threshold in seconds; defaults to 900.0 (15 min).
    """
    if not timestamps:
        return False
    return (now - max(timestamps)) > silence
