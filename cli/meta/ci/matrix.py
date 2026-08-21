"""Build the CI deploy matrix of one sweep, chunk by chunk.

Usage:
  python -m cli.meta.ci.matrix --index N [--sweep S] [--modes auto]
      [--whitelist "..."] [--priority "..."] [--lifecycles "..."] [--tor auto]
      [--distros "..."] [--filesystem "..."]

This is the pipeline the deploy jobs discover through, and the single place
the run's shape is decided:

1. Two discovery queries, keeping today's filter semantics: the priority line
   is queried on its own whitelist so priority roles run even when the
   diff-derived whitelist would not have selected them, and the regular line
   is queried on the effective whitelist with the priority rows withdrawn.
   Concatenated, they are the sweep's ordered candidate list. Both lists are
   selection tokens (:mod:`utils.github.variant.selection`): what a token pins
   narrows the row, what it leaves open the line decides as it always did.
2. Every row is assigned its deploy mode, tor state, distro and filesystem by
   its position in that list (:mod:`utils.github.variant.axes`).
3. The list is cut into serial chunks with a hard boundary at the
   priority/regular seam (:mod:`cli.meta.ci.chunks`), sized by the run's job
   and queue budget (:mod:`cli.meta.ci.slots`).

``--index`` then prints one chunk as the matrix JSON. Every chunk block runs
the same computation and takes its own slice, so the blocks agree without
passing state between them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from cli.meta.ci import chunks, query, slots
from utils.cache.applications import get_variants
from utils.github.variant import axes, pools, selection, tor
from utils.roles.display import display_names

DROPPED = ("priority", "weight", "id", "covered", "clone")
"""Entry keys the plan table reads but the matrix JSON withholds, so a deploy
job cannot reference one: they describe the row's rank, not its deployment."""


def candidates(
    *,
    modes: tuple[str, ...],
    whitelist: str,
    priority: str,
    lifecycles: str,
) -> list[dict]:
    """The sweep's ordered candidate rows: priority line first, then the
    regular line, each annotated with the modes it offers and whether it is
    priority."""
    leading = selection.parse_list(priority)
    keep = selection.parse_list(whitelist)
    rows: list[dict] = []
    if leading:
        rows += [
            {**row, "priority": True}
            for row in selection.apply(
                query.discover_rows(
                    modes, whitelist=selection.names(leading), lifecycles=lifecycles
                ),
                leading,
            )
        ]
    pinned = {(pin.app, variant) for pin in leading for variant in pin.variants}
    regular = [
        row
        for row in query.discover_rows(
            modes,
            whitelist=selection.names(keep),
            blacklist=selection.names(pin for pin in leading if not pin.variants),
            lifecycles=lifecycles,
        )
        if (row["name"], row.get("variant")) not in pinned
    ]
    rows += [{**row, "priority": False} for row in selection.apply(regular, keep)]
    return [{**row, "modes": query.row_modes(row, modes)} for row in rows]


def entries_of(
    *,
    modes: tuple[str, ...],
    whitelist: str,
    priority: str,
    lifecycles: str,
    sweep: int,
    tor_mode: str,
    distros: tuple[str, ...],
    filesystems: tuple[str, ...],
) -> list[dict[str, str]]:
    """Every candidate row of the sweep, axes assigned, in global order."""
    return axes.assign(
        candidates(
            modes=modes,
            whitelist=whitelist,
            priority=priority,
            lifecycles=lifecycles,
        ),
        sweep=sweep,
        tor_mode=tor_mode,
        distros=distros,
        filesystems=filesystems,
        variants_per_app=get_variants(),
    )


def resolve_offset(raw: int | str | None = None) -> str:
    """The offset a run was given, as written. ``None`` reads
    ``INFINITO_CI_OFFSET``; :func:`offset_index` decides what it means."""
    if raw is None:
        raw = os.environ.get("INFINITO_CI_OFFSET")
    return "" if raw is None else str(raw).strip()


def offset_index(raw: int | str | None, regular: list[dict[str, str]]) -> int:
    """Where the regular chunks start reading.

    A number is that many rows; anything else is a selection token
    (:mod:`utils.github.variant.selection`) and the start is the first regular
    row it names. Resuming at a role beats counting rows by hand: the ranking
    shifts whenever a variant is added, so the index that meant 'carry on
    behind nextcloud' yesterday means something else today, while the token
    still says it.

    Args:
        raw: the ``offset`` input, a count or a token.
        regular: the regular line in ranking order.

    Raises:
        SystemExit: a token that names no regular row. Starting at 0 instead
            would silently redeploy the head an operator meant to skip.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return 0
    if text.lstrip("+-").isdigit():
        return max(int(text), 0)
    pin = selection.parse(text)
    for index, entry in enumerate(regular):
        if selection.covers(pin, entry):
            return index
    raise SystemExit(
        f"offset {selection.describe(pin)!r} names no row of the regular line; "
        f"it is on the priority line, outside the run's filters, or gone"
    )


def redundant(entry: dict[str, str]) -> bool:
    """Whether the sweep drops this row as coverage an earlier row already has."""
    if entry["priority"] == "true":
        return False
    return entry["clone"] == "true" or entry["covered"] != "0"


def chunks_of(
    entries: list[dict[str, str]], offset: int | str | None = 0
) -> list[list[dict[str, str]]]:
    """Cut the sweep's entries into its chunks, priority blocks first.

    Chunk 0 holds the head of the ranking unless *offset* moves it; the order
    *inside* a chunk is then sorted
    (:func:`utils.github.variant.axes.sort_key`), so the job list reads by role
    rather than by rank."""
    regular = [
        entry
        for entry in entries
        if entry["priority"] != "true" and not redundant(entry)
    ]
    return [
        sorted(chunk, key=axes.sort_key)
        for chunk in chunks.plan(
            [entry for entry in entries if entry["priority"] == "true"],
            regular,
            size=slots.chunk_size(),
            blocks=slots.chunk_count(),
            budget=slots.available(),
            offset=offset_index(offset, regular),
        )
    ]


def build_sweep(
    *,
    modes: tuple[str, ...],
    whitelist: str,
    priority: str,
    lifecycles: str,
    sweep: int,
    tor_mode: str,
    distros: tuple[str, ...],
    filesystems: tuple[str, ...],
    offset: int = 0,
) -> list[list[dict[str, str]]]:
    """Every chunk of the sweep, priority blocks first."""
    return chunks_of(
        entries_of(
            modes=modes,
            whitelist=whitelist,
            priority=priority,
            lifecycles=lifecycles,
            sweep=sweep,
            tor_mode=tor_mode,
            distros=distros,
            filesystems=filesystems,
        ),
        offset,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the CI deploy matrix of one sweep chunk."
    )
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--sweep", type=int, default=None)
    parser.add_argument("--modes", default=query.ALL_MODES)
    parser.add_argument("--whitelist", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--lifecycles", default="")
    parser.add_argument("--tor", default=None)
    parser.add_argument("--distros", default="")
    parser.add_argument("--filesystem", default="")
    parser.add_argument("--offset", default=None)
    args = parser.parse_args(argv)

    codec = display_names()
    if args.lifecycles.strip():
        os.environ["INFINITO_LIFECYCLES"] = args.lifecycles

    sweep = axes.resolve_sweep() if args.sweep is None else args.sweep
    plan = build_sweep(
        modes=query.resolve_modes(args.modes),
        whitelist=codec.decode_list(args.whitelist),
        priority=codec.decode_list(args.priority),
        lifecycles=args.lifecycles,
        sweep=sweep,
        tor_mode=tor.resolve_tor_mode(args.tor),
        distros=pools.resolve_distros(args.distros),
        filesystems=pools.resolve_filesystems(args.filesystem),
        offset=resolve_offset(args.offset),
    )
    chunk = plan[args.index] if 0 <= args.index < len(plan) else []
    print(json.dumps([{k: v for k, v in e.items() if k not in DROPPED} for e in chunk]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
