"""Writer sampling during faults and the pure analysis of the samples."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class Round:
    """One sampling round.

    Args:
        at_ms: epoch ms the round started.
        writers: instance -> True (writer), False (not) or None (unreachable).
        gtids: instance -> ``@@gtid_current_pos`` text, or None.
    """

    at_ms: int
    writers: dict[str, bool | None]
    gtids: dict[str, str | None] = field(default_factory=dict)

    def writer_set(self) -> set[str]:
        return {name for name, state in self.writers.items() if state}


def dual_writer_windows(rounds: list[Round]) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` epoch-ms stretches with two or more writers.

    A stretch starts at the first round with two writers and ends at the first
    round after it with fewer, or at the last round.
    """
    windows: list[tuple[int, int]] = []
    start: int | None = None
    for current in rounds:
        if len(current.writer_set()) >= 2:
            if start is None:
                start = current.at_ms
        elif start is not None:
            windows.append((start, current.at_ms))
            start = None
    if start is not None:
        windows.append((start, rounds[-1].at_ms))
    return windows


def dual_writer_detail(rounds: list[Round], limit: int = 5) -> str:
    """Name the writers of each two-writer round and the wait until the next round.

    A long wait means the sampler lost rounds (a paused node fails them), so
    the stretch it reports may be one round wide in truth.

    Args:
        rounds: samples in time order.
        limit: how many two-writer rounds to describe.
    """
    parts = []
    for index, current in enumerate(rounds):
        if len(current.writer_set()) < 2:
            continue
        following = (
            rounds[index + 1].at_ms if index + 1 < len(rounds) else current.at_ms
        )
        parts.append(
            f"{'+'.join(sorted(current.writer_set()))} at {current.at_ms}, "
            f"next round {(following - current.at_ms) / 1000.0:.1f}s later"
        )
    return "; ".join(parts[:limit])


def first_new_writer(
    rounds: list[Round], *, after_ms: int, old: str
) -> tuple[str, int] | None:
    """Return the first instance other than ``old`` seen as writer after a fault.

    Args:
        rounds: samples in time order.
        after_ms: epoch ms of the fault.
        old: instance that was writer before the fault.
    """
    for current in rounds:
        if current.at_ms < after_ms:
            continue
        others = sorted(current.writer_set() - {old})
        if others:
            return others[0], current.at_ms
    return None


def gtid_total(text: str | None) -> int | None:
    """Order a GTID position the way the elector does: the sum of sequences.

    Returns None for an unreadable position.
    """
    if text is None:
        return None
    total = 0
    for gtid in filter(None, (part.strip() for part in text.split(","))):
        pieces = gtid.split("-")
        if len(pieces) != 3 or not all(piece.isdigit() for piece in pieces):
            return None
        total += int(pieces[2])
    return total


def gtid_choice_violation(
    rounds: list[Round], *, fault_ms: int, old: str
) -> str | None:
    """Return why the promoted MariaDB instance was behind, or None.

    The promoted instance's position at its first writer sample is compared
    with the highest position any other surviving instance showed between the
    fault and the round before that promotion. The promotion round itself is
    left out for the others: a peer sampled after the winner may already hold
    the winner's own first writes.

    Args:
        rounds: samples with ``gtids`` filled, in time order.
        fault_ms: epoch ms of the fault on the old writer.
        old: the old writer, excluded from the comparison.
    """
    promoted = first_new_writer(rounds, after_ms=fault_ms, old=old)
    if promoted is None:
        return "no instance was promoted after the fault"
    winner, at_ms = promoted
    window = [r for r in rounds if fault_ms <= r.at_ms <= at_ms]
    winner_total = next(
        (
            gtid_total(r.gtids.get(winner))
            for r in reversed(window)
            if gtid_total(r.gtids.get(winner)) is not None
        ),
        None,
    )
    if winner_total is None:
        return f"{winner} was promoted without a readable GTID position"
    best_name, best_total = None, -1
    for current in window:
        if current.at_ms == at_ms:
            continue
        for name, text in current.gtids.items():
            total = gtid_total(text)
            if name in (winner, old) or total is None:
                continue
            if total > best_total:
                best_name, best_total = name, total
    if best_name is not None and best_total > winner_total:
        return (
            f"{winner} was promoted at GTID total {winner_total} while {best_name} "
            f"was at {best_total}"
        )
    return None


class Sampler:
    """Collect rounds on a background thread until stopped.

    Args:
        sample: returns one ``Round`` per call.
        interval_s: pause between two rounds.
    """

    def __init__(self, sample: Callable[[], Round], interval_s: float = 1.0):
        self._sample = sample
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rounds: list[Round] = []
        self.errors: list[str] = []

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.rounds.append(self._sample())
            except (RuntimeError, OSError) as exc:
                self.errors.append(str(exc))
            self._stop.wait(self._interval)

    def start(self) -> Sampler:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> list[Round]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=60)
        return list(self.rounds)


def epoch_ms() -> int:
    return int(time.time() * 1000)
