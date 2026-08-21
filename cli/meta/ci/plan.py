"""Render the plan of one CI sweep: every candidate row, and where it lands.

Usage:
  python -m cli.meta.ci.plan [--distros "debian"] [--filesystem "zfs"]
      [--whitelist "..."] [--priority "..."] [--modes auto]
      [--lifecycles "..."] [--sweep N] [--cli]

The plan runs the same pipeline the deploy jobs discover through
(``cli.meta.ci.matrix``), so what the table shows and what CI deploys cannot
diverge. One row per ``role#variant`` candidate in global query order, with
the chunk it falls into and the axes it was assigned.

Status per row: ⭐ a priority row, ✅ deployed by this sweep, ❌ beyond the
sweep's budget (raise ``--offset`` to reach it), ✂️ cut as redundant coverage —
a clone or a row an earlier one already embeds, which no sweep deploys.
``--cli`` renders fixed-width terminal tables instead of Markdown.

🆔 numbers the rows of this table, 1..n, and 🔰 names the 🆔 of the earlier row
that already embeds this one -- empty when nothing does. A row with a 🔰 is
redundant coverage: whatever it would prove, the row it points at proves first. 🐑 marks the other reason a row is cut: it
shares its service set with an earlier role, which stands in for it.
"""

from __future__ import annotations

import argparse
import os
import sys

from cli.meta.ci import matrix, query, slots
from cli.meta.roles.applications.complexity.render import _dwidth
from utils.github.variant import axes, pools, tor
from utils.roles.display import display_names
from utils.symbol_glossary import to_emoji

_STAR = to_emoji("priority")
_OK = to_emoji("enabled")
_OFF = to_emoji("disabled")
_CUT = to_emoji("redundant")

_COLUMNS = (
    "id",
    "chunk",
    "name",
    "variant",
    "mode",
    "distro",
    "filesystem",
    "tor",
    "triggered",
    "covered_by",
    "weight",
    "clone",
)
_GLYPH = {"triggered": "enabled", "distro": "distros"}
_HEADERS = tuple(
    f"{to_emoji(_GLYPH.get(key, key))} {key.replace('_', ' ').capitalize()}"
    for key in _COLUMNS
)


def _key(entry: dict[str, str]) -> tuple[str, ...]:
    """What identifies one deploy row: every axis it was assigned.

    A priority role runs every combination of its variant, and a selection can
    ask for one variant on two distros, so app+variant alone matches several
    rows and would report the first one's chunk for all of them -- including
    for rows the budget never reaches, which the table would then mark as
    deployed.
    """
    return (
        entry["apps"],
        entry["variant"],
        entry["mode"],
        entry["tor"],
        entry["distro"],
        entry["filesystem"],
    )


def _chunk_of(entry: dict[str, str], plan: list[list[dict[str, str]]]) -> int | None:
    """Index of the chunk *entry* landed in, or ``None`` when this sweep
    leaves it to the next one."""
    key = _key(entry)
    for index, chunk in enumerate(plan):
        if any(_key(row) == key for row in chunk):
            return index
    return None


def cells(
    entries: list[dict[str, str]],
    plan: list[list[dict[str, str]]],
) -> list[tuple[str, ...]]:
    rows = []
    positions: dict[str, str] = {}
    for counter, entry in enumerate(entries, start=1):
        positions.setdefault(entry.get("id", ""), str(counter))
    for counter, entry in enumerate(entries, start=1):
        chunk = _chunk_of(entry, plan)
        if matrix.redundant(entry):
            status, where = _CUT, ""
        elif chunk is None:
            status, where = _OFF, ""
        else:
            status = _STAR if entry["priority"] == "true" else _OK
            where = str(chunk)
        covered = entry.get("covered", "0")
        rows.append(
            (
                str(counter),
                where,
                entry["apps"],
                entry["variant"],
                to_emoji(entry["mode"]),
                to_emoji(entry["distro"]),
                to_emoji(entry["filesystem"]),
                to_emoji("tor" if entry["tor"] == "true" else "clearnet"),
                status,
                positions.get(covered, covered) if covered not in ("", "0") else "",
                entry["weight"],
                to_emoji("clone") if entry.get("clone") == "true" else "",
            )
        )
    return rows


def _title(plan: list[list[dict[str, str]]], sweep: int) -> str:
    sizes = ", ".join(str(len(chunk)) for chunk in plan) or "-"
    return (
        f"sweep {sweep} · chunk size {slots.chunk_size()} "
        f"· {len(plan)} chunk(s) [{sizes}] · budget {slots.available()}"
    )


def render_markdown(title: str, rows: list[tuple[str, ...]]) -> str:
    lines = [
        "## Plan 🗺️",
        "",
        f"### {title}",
        "",
        "| " + " | ".join(_HEADERS) + " |",
        "|" + "---|" * len(_HEADERS),
    ]
    lines += ["| " + " | ".join(cell) + " |" for cell in rows]
    return "\n".join(lines)


def _pad(value: str, width: int) -> str:
    return value + " " * max(width - _dwidth(value), 0)


def render_cli(title: str, rows: list[tuple[str, ...]]) -> str:
    widths = [
        max([_dwidth(header), *(_dwidth(cell[i]) for cell in rows)])
        for i, header in enumerate(_HEADERS)
    ]
    header = "  ".join(_pad(h, w) for h, w in zip(_HEADERS, widths, strict=True))
    rule = "  ".join("-" * w for w in widths)
    body = [
        "  ".join(_pad(value, w) for value, w in zip(cell, widths, strict=True))
        for cell in rows
    ]
    return "\n".join([title, header, rule, *body])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the plan of one CI sweep.")
    parser.add_argument("--distros", default="")
    parser.add_argument("--whitelist", default="")
    parser.add_argument("--priority", default="")
    parser.add_argument("--modes", default=query.ALL_MODES)
    parser.add_argument("--lifecycles", default="")
    parser.add_argument("--sweep", type=int, default=None)
    parser.add_argument("--tor", default=None)
    parser.add_argument("--filesystem", default="")
    parser.add_argument("--offset", default=None)
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args(argv)

    codec = display_names()
    if args.lifecycles.strip():
        os.environ["INFINITO_LIFECYCLES"] = args.lifecycles

    sweep = axes.resolve_sweep() if args.sweep is None else args.sweep
    entries = matrix.entries_of(
        modes=query.resolve_modes(args.modes),
        whitelist=codec.decode_list(args.whitelist),
        priority=codec.decode_list(args.priority),
        lifecycles=args.lifecycles,
        sweep=sweep,
        tor_mode=tor.resolve_tor_mode(args.tor),
        distros=pools.resolve_distros(args.distros),
        filesystems=pools.resolve_filesystems(args.filesystem),
    )
    plan = matrix.chunks_of(entries, matrix.resolve_offset(args.offset))
    rows = cells(entries, plan)

    render = render_cli if args.cli else render_markdown
    print(render(_title(plan, sweep), rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
