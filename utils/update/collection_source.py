"""Which requirements source ``scripts/install/ansible.sh`` should try first.

Both sources carry the same pinned collections, so the only thing separating
them is how long they take and whether they answer at all. A single slow day
says nothing: galaxy.ansible.com degrades and recovers, and a git clone can
stall on one runner. The default is therefore retuned only when a rolling
window of daily samples shows one source durably behind the other.

A sample whose install failed is recorded as ``None`` and ranks worse than
any duration, so an outage counts fully rather than being dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SOURCES = ("galaxy", "git")
WINDOW = 12
"""Samples the median is taken over; below this the default is left alone."""

RATIO = 3.0
"""How many times slower the preferred source must be before it is swapped."""


@dataclass(frozen=True)
class Verdict:
    """The outcome of comparing the two sources.

    Args:
        preferred: the source in force when the comparison ran.
        proposed: the source the samples favour, equal to preferred when
            nothing should change.
        medians: median seconds per source, infinite when every sample failed.
        samples: how many samples the medians were taken over.
    """

    preferred: str
    proposed: str
    medians: dict[str, float]
    samples: int

    @property
    def changed(self) -> bool:
        return self.proposed != self.preferred


def load_history(path: Path) -> list[dict[str, float | None]]:
    """Samples recorded so far, oldest first, or an empty list.

    Args:
        path: JSON file holding the rolling window.
    """
    try:
        raw = path.read_text()  # nocheck: cache-read -- rewritten every run
        payload = json.loads(raw)
    except (OSError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def append_sample(
    history: list[dict[str, float | None]], sample: dict[str, float | None]
) -> list[dict[str, float | None]]:
    """The history with SAMPLE appended, truncated to the newest WINDOW entries.

    Args:
        history: samples recorded so far, oldest first.
        sample: seconds per source for this run, None where the install failed.
    """
    return [*history, sample][-WINDOW:]


def _median_seconds(history: list[dict[str, float | None]], source: str) -> float:
    values = [
        float("inf") if entry.get(source) is None else float(entry[source])
        for entry in history
    ]
    return median(values) if values else float("inf")


def decide(history: list[dict[str, float | None]], preferred: str) -> Verdict:
    """Whether the samples justify swapping the preferred source.

    Args:
        history: samples recorded so far, oldest first.
        preferred: the source currently tried first.
    """
    medians = {source: _median_seconds(history, source) for source in SOURCES}
    verdict = Verdict(
        preferred=preferred,
        proposed=preferred,
        medians=medians,
        samples=len(history),
    )
    if len(history) < WINDOW:
        return verdict

    other = next(source for source in SOURCES if source != preferred)
    mine, theirs = medians[preferred], medians[other]
    if theirs == float("inf") or theirs <= 0:
        return verdict
    if mine >= theirs * RATIO:
        return Verdict(
            preferred=preferred,
            proposed=other,
            medians=medians,
            samples=len(history),
        )
    return verdict
