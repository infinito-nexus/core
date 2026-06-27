"""Argument parsing, sorting/filtering and the ``main`` entry point."""

from __future__ import annotations

import argparse
import sys

from utils import PROJECT_ROOT

from .model import ComplexityRow, compute_complexity_rows
from .render import render_json, render_string, render_table

_SORT_KEYS = {
    "embeds": lambda r: (r.embeds, r.name),
    "consumers": lambda r: (r.consumers, r.name),
    "total": lambda r: (r.total, r.name),
    "name": lambda r: (r.name,),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="infinito meta roles applications complexity",
        description=(
            "For every application role, list its transitively resolved "
            "shared-service dependencies and the resulting complexity score."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--sort",
        choices=tuple(_SORT_KEYS),
        default="embeds",
        help=(
            "Sort column. 'embeds' (default) is the count of service "
            "deps the role embeds; 'consumers' is the count of roles "
            "that embed this one; 'total' is the sum of direct + "
            "transitive in both directions; 'name' sorts alphabetically."
        ),
    )
    p.add_argument(
        "--order",
        choices=("asc", "desc"),
        default="asc",
        help="Sort direction. 'asc' (default) puts the lowest values first.",
    )
    p.add_argument(
        "--filter",
        default=None,
        metavar="SUBSTRING",
        help=(
            "Show only roles whose name contains SUBSTRING (case-"
            "insensitive). The complexity scores are computed against "
            "the full role tree first; only the rendered rows are "
            "filtered, so a role's transitive consumer / embed counts "
            "still reflect the whole codebase."
        ),
    )
    p.add_argument(
        "--unique",
        action="store_true",
        help=(
            "Collapse roles that share a 'base' (same name+services "
            "cluster): keep the first per base in sort order and hide "
            "the rest. Their 'siblings' column still names what was "
            "hidden."
        ),
    )
    p.add_argument(
        "--no-group-names",
        action="store_true",
        help=(
            "Ignore services whose enabled/shared flag is the "
            "'<role>' in group_names Jinja form. Only literal `true` "
            "flags count as deps."
        ),
    )
    p.add_argument(
        "--format",
        choices=("cli", "json", "string"),
        default="cli",
        help=(
            "Output format. 'cli' (default) shows counts only (name, "
            "embeds, consumers, base, siblings) for a compact terminal "
            "view. 'json' emits the full payload including the resolved "
            "service, consumer and sibling role lists. 'string' prints "
            "only the role names, one per line (feed into `make "
            "roundtrip apps=...`)."
        ),
    )
    p.add_argument(
        "-L",
        "--level",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Limit recursion depth: 1 = direct deps only, 2 = direct + "
            "their direct, ... Default: unbounded (full closure)."
        ),
    )
    return p


def _unique_by_base(rows: list[ComplexityRow]) -> list[ComplexityRow]:
    seen: set[str] = set()
    kept: list[ComplexityRow] = []
    for row in rows:
        if row.base in seen:
            continue
        seen.add(row.base)
        kept.append(row)
    return kept


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)

    if args.level is not None and args.level < 1:
        p.error("--level/-L must be >= 1")

    roles_dir = PROJECT_ROOT / "roles"
    if not roles_dir.is_dir():
        print(f"Error: roles directory not found: {roles_dir}", file=sys.stderr)
        return 1

    rows = compute_complexity_rows(
        roles_dir,
        include_group_names=not args.no_group_names,
        max_level=args.level,
    )

    rows.sort(key=_SORT_KEYS[args.sort], reverse=args.order == "desc")

    if args.filter:
        needle = args.filter.lower()
        rows = [r for r in rows if needle in r.name.lower()]

    if args.unique:
        rows = _unique_by_base(rows)

    if args.format == "json":
        rendered = render_json(rows)
    elif args.format == "string":
        rendered = render_string(rows)
    else:
        rendered = render_table(rows)
    if rendered:
        print(rendered)
    return 0
