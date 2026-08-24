"""Split the ordered discovery rows into the serial chunks of one sweep.

A *sweep* is one orchestrator run. It deploys its rows in serial chunk
blocks, each small enough that its last runner wave still starts inside the
queue window (:mod:`cli.meta.ci.slots` sizes them). Two rules shape the split:

* **Priority first, never mixed.** Priority rows sort to the head of the list
  and the split forces a chunk boundary at the priority/regular seam, so a
  chunk is either all priority or all regular. The seam chunk stays short
  rather than being topped up with regular rows -- that is what guarantees
  every priority row is done before the first regular one starts. Priority is
  never subject to the sweep offset: it leads every sweep.

* **The head leads unless an operator says otherwise.** Chunk 0 starts at the
  top of the ranking. The list is ordered coverage-first, so its head is what a
  run most needs proven, and a sweep that cannot afford the whole list leaves
  the tail behind rather than sliding a window over it.

  ``offset`` moves that start deliberately: it is how an operator reaches the
  tail without waiting for anything. It defaults to 0, so every run that does
  not ask for it deploys the same head and can be compared against the last
  one. This used to be derived from the sweep number instead, which bought tail
  coverage at the price of the head -- chunk 0 began wherever the arithmetic
  pointed, the rows that matter most ran only every few sweeps, and no two runs
  were comparable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TypeVar

    T = TypeVar("T")


def slice_chunks(rows: Sequence[T], size: int) -> list[list[T]]:
    """Cut *rows* into consecutive blocks of at most *size*."""
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    return [list(rows[start : start + size]) for start in range(0, len(rows), size)]


def plan(
    priority: Sequence[T],
    regular: Sequence[T],
    *,
    size: int,
    blocks: int,
    budget: int,
    offset: int = 0,
) -> list[list[T]]:
    """The chunks one sweep deploys, priority blocks first.

    Args:
        priority: rows of the priority line, in query order.
        regular: rows of the regular line, in query order.
        size: rows one chunk may hold (``slots.chunk_size``).
        blocks: chunk blocks the workflow declares (``slots.chunk_count``).
        budget: rows the run job cap allows in total (``slots.available``).
        offset: how many regular rows to skip before filling the chunks. ``0``
            (the default) starts at the head of the ranking. A value past the
            end of the list leaves the regular chunks empty rather than
            wrapping: an operator who asks for a window beyond the tail gets an
            empty run, not a silent restart at the top.

    Returns:
        at most *blocks* chunks, none larger than *size*, together holding at
        most *budget* rows. Priority chunks come first and are never topped up
        with regular rows.
    """
    priority_chunks = slice_chunks(priority[:budget], size)[:blocks]
    spent = sum(len(chunk) for chunk in priority_chunks)
    capacity = max(min((blocks - len(priority_chunks)) * size, budget - spent), 0)
    if not capacity or not regular:
        return priority_chunks
    start = max(offset, 0)
    return priority_chunks + slice_chunks(regular[start : start + capacity], size)
