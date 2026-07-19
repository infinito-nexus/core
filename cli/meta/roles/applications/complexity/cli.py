"""Argument parsing, sorting/filtering and the ``main`` entry point."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from utils import PROJECT_ROOT

from .filter import FilterError, compile_predicate
from .model import (
    TESTED_LIFECYCLES,
    ComplexityRow,
    compute_complexity_rows,
    compute_variant_complexity_rows,
)
from .render import render_json, render_string, render_table, render_yaml

_SORT_KEYS = {
    "embeds": lambda r: r.embeds,
    "consumers": lambda r: r.consumers,
    "weight": lambda r: r.weight,
    "name": lambda r: r.name,
    "random": lambda r: r.random,
    "variant": lambda r: r.variant if r.variant is not None else -1,
    "variants": lambda r: r.variants,
    "bundles": lambda r: r.bundles,
    "id": lambda r: r.id,
    "covered_by": lambda r: r.covered_by,
    "jobs": lambda r: r.jobs,
    "lifecycle": lambda r: r.lifecycle,
    "compose": lambda r: int(r.compose),
    "swarm": lambda r: int(r.swarm),
    "host": lambda r: int(r.host),
    "stack": lambda r: int(r.stack),
    "test_compose": lambda r: int(r.test_compose),
    "test_swarm": lambda r: int(r.test_swarm),
    "test_host": lambda r: int(r.test_host),
    "integrated": lambda r: int(r.integrated),
    "tested_elsewhere": lambda r: int(r.test_compose or r.test_swarm),
    "clone": lambda r: int(r.clone),
}


def _row_fields(r: ComplexityRow) -> dict[str, Any]:
    """The ``--filter`` view of a row: scalar fields keyed by name. ``row`` and
    ``jobs`` are excluded (not assigned until after filtering)."""
    return {
        "name": r.name,
        "lifecycle": r.lifecycle,
        "dna": r.dna,
        "clone": r.clone,
        "embeds": r.embeds,
        "embeds_direct": r.embeds_direct,
        "consumers": r.consumers,
        "consumers_direct": r.consumers_direct,
        "weight": r.weight,
        "variants": r.variants,
        "bundles": r.bundles,
        "id": r.id,
        "covered_by": r.covered_by,
        "variant": r.variant if r.variant is not None else -1,
        "siblings": len(r.siblings),
        "random": r.random,
        "compose": r.compose,
        "swarm": r.swarm,
        "host": r.host,
        "stack": r.stack,
        "test_compose": r.test_compose,
        "test_swarm": r.test_swarm,
        "test_host": r.test_host,
        "integrated": r.integrated,
    }


FILTER_FIELDS = frozenset(
    _row_fields(ComplexityRow("", 0, [], 0, [], 0, [], 0, [], 0, "", []))
)

_DIRECTIONS = {"asc": False, "desc": True}

DEFAULT_SORT = "asc embeds"


def parse_lifecycles(tokens: list[str] | None) -> set[str] | None:
    """Normalise ``--lifecycles`` tokens into a lowercase set, splitting each on
    commas and whitespace so ``'alpha,beta'`` and ``'alpha beta'`` are
    equivalent. ``None`` (flag absent) stays ``None`` so the model falls back to
    its built-in default envelope."""
    if not tokens:
        return None
    values = {
        part.strip().lower()
        for token in tokens
        for part in re.split(r"[,\s]+", token)
        if part.strip()
    }
    return values or None


def parse_sort_spec(spec: str) -> list[tuple[str, bool]]:
    """Parse a ``--sort`` value into an ordered ``[(column, reverse), ...]``.

    Args:
        spec: Comma-separated clauses, each a column optionally prefixed or
            suffixed with a direction, e.g. ``"desc embeds, asc total"``.
            Direction defaults to ``asc``.

    Returns:
        Clauses in significance order (first = primary sort key). ``reverse``
        is True for ``desc``.

    Raises:
        ValueError: An unknown token, or a clause naming no column.
    """
    out: list[tuple[str, bool]] = []
    for clause in spec.split(","):
        tokens = clause.split()
        if not tokens:
            continue
        reverse = False
        column: str | None = None
        for token in tokens:
            low = token.lower()
            if low in _DIRECTIONS:
                reverse = _DIRECTIONS[low]
            elif low in _SORT_KEYS:
                column = low
            else:
                raise ValueError(
                    f"invalid --sort token {token!r}; expected a direction "
                    f"(asc/desc) or a column ({', '.join(_SORT_KEYS)})"
                )
        if column is None:
            raise ValueError(f"--sort clause {clause!r} names no column")
        out.append((column, reverse))
    if not out:
        raise ValueError("--sort requires at least one column")
    return out


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
        default=DEFAULT_SORT,
        metavar="SPEC",
        help=(
            "Sort order: comma-separated columns, each optionally prefixed "
            "with a direction, applied in order so later columns break ties "
            "of earlier ones. e.g. 'desc embeds, asc weight' sorts by embeds "
            "descending, then by weight ascending within equal embeds. "
            "Direction defaults to 'asc'. Columns: 'embeds' (service deps the "
            "role embeds), 'consumers' (roles that embed this one), "
            "'weight' (sum of direct + transitive in both directions), "
            "'name' (alphabetical), 'random' (the per-row nonce), 'variant' / "
            "'variants' (the variant index / the role's variant count), "
            "'bundles' (the role's compose bundle/job count), 'id', "
            "'covered_by' and 'jobs' (assigned after the coverage pass, so "
            "sorting by them reorders within the ties of the more significant "
            f"keys). Default: {DEFAULT_SORT!r}."
        ),
    )
    p.add_argument(
        "--variant",
        action="store_true",
        help=(
            "List each role's meta/variants.yml variants individually "
            "instead of the whole role: one row per variant, its 'embeds' "
            "recomputed from that variant's enabled+shared service flags. "
            "The 'variant' column shows the variant index. Roles keep their "
            "role-level consumer counts."
        ),
    )
    p.add_argument(
        "--filter",
        default=None,
        metavar="EXPR",
        help=(
            "Boolean filter expression over row fields. Operators: '%%' "
            "(contains / set membership), '==' '!=' '<' '>' '<=' '>=', "
            "combined with 'and' 'or' 'xor' 'not' and parentheses; set "
            "literals like {alpha,beta} are allowed. Fields: name, "
            "lifecycle, base, embeds, embeds_direct, consumers, "
            "consumers_direct, weight, variants, bundles, id, covered_by, "
            "variant, siblings, random, compose, swarm, stack. "
            "compose/swarm/stack are "
            "booleans (compare with ==true / ==false). 'stack' is True when the "
            "role ships its own compose stack template. "
            "String compares are "
            "case-"
            "insensitive. A bare word (no operator) means 'name %% word'. "
            "e.g. 'lifecycle == beta and weight > 50', "
            '"lifecycle %% {alpha,pre} or name %% ldap". Scores are '
            "computed against the full role tree first; only the rendered "
            "rows are filtered."
        ),
    )
    p.add_argument(
        "--deploy-mode",
        choices=("compose", "swarm", "host"),
        default="compose",
        help=(
            "Deploy mode the 'bundles'/'jobs' columns count CI runners for "
            "(whole-role mode only): 'compose' (default) packs variants into "
            "size/storage bundles; 'swarm' counts one runner per deployable "
            "variant. Drives the --max-jobs budget per mode."
        ),
    )
    p.add_argument(
        "--lifecycles",
        nargs="+",
        default=None,
        metavar="STAGE",
        help=(
            "Lifecycle envelope the 'compose'/'swarm' columns treat as "
            "CI-tested: a role scores True for a mode only if its "
            "meta/services.yml lifecycle is in this set (and it is invokable "
            "and not skipped for the mode). Comma- or whitespace-separated, "
            "e.g. 'alpha beta rc stable' or 'alpha,beta'. Omitted: the "
            f"built-in default ({' '.join(sorted(TESTED_LIFECYCLES))})."
        ),
    )
    p.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Hard-cut the output once the cumulative 'jobs' (running sum of "
            "'bundles' down the sorted/filtered rows) reaches N: keep only the "
            "leading rows whose cumulative job count stays below N. Use to cap "
            "a CI run's total deploy jobs. Combine with a coverage-first sort "
            "(e.g. 'asc covered_by, desc weight') to keep the highest-value "
            "jobs under the budget."
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
        choices=("cli", "json", "yaml", "string"),
        default="cli",
        help=(
            "Output format. 'cli' (default) shows counts only (name, "
            "embeds, consumers, base, siblings) for a compact terminal "
            "view. 'json' / 'yaml' emit the full payload including the "
            "resolved service, consumer and sibling role lists. 'string' "
            "prints only the role names, one per line (feed into `make "
            "roundtrip apps=...`)."
        ),
    )
    p.add_argument(
        "-s",
        "--symbol",
        action="store_true",
        help=(
            "Compact emoji view of the 'cli' table: emoji-only headers, "
            "true/false as ✅/❌, and lifecycle stages as symbols. No effect on "
            "the json/yaml/string formats."
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


def _apply_sort(rows: list[ComplexityRow], sort_spec: list[tuple[str, bool]]) -> None:
    """Stable multi-key sort in place: ``name`` as the deterministic least-
    significant fallback, then each spec clause from least to most significant.
    Run once before ``_mark_covered`` (where the ``id``/``covered_by`` keys are
    still unset and sort as a no-op) and once after (where they order rows by
    the just-computed coverage)."""
    rows.sort(key=_SORT_KEYS["name"])
    for column, reverse in reversed(sort_spec):
        rows.sort(key=_SORT_KEYS[column], reverse=reverse)


def _mark_covered(rows: list[ComplexityRow]) -> list[ComplexityRow]:
    """Assign each sorted row its numeric ``id`` (its position in sort order)
    and its ``covered_by`` via a greedy set-cover: the first row is green, and
    every later row's ``covered_by`` is the (1-based) ``id`` of the first
    already-green predecessor OF A DIFFERENT ROLE that actually embeds this row
    (its role name is in the predecessor's transitive ``services``); a row with
    no such predecessor becomes green itself, leaving ``covered_by`` at the
    sentinel ``0`` (no real ``id`` is 0). Because ``services`` is the
    transitive closure, embedding the row pulls its whole subtree, so the
    coverer's deploy genuinely brings this row up. Two variants of the same
    role never cover each other (a role never embeds itself).

    Coverage is variant-aware: when a service.yml declares another service
    enabled+shared it always pulls that provider's variant 0, so only a row's
    variant-0 (or whole-role) form can be covered. A variant > 0 row is never
    covered and is always green; it may still cover other roles' rows."""
    green: list[tuple[int, str, set[str]]] = []
    out: list[ComplexityRow] = []
    for index, row in enumerate(rows, start=1):
        coverable = row.variant in (None, 0)
        coverer = (
            next(
                (
                    gid
                    for gid, gname, gset in green
                    if gname != row.name and row.name in gset
                ),
                None,
            )
            if coverable
            else None
        )
        if coverer is None:
            green.append((index, row.name, set(row.services)))
        out.append(row._replace(id=index, covered_by=coverer or 0))
    return out


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)

    if args.level is not None and args.level < 1:
        p.error("--level/-L must be >= 1")

    if args.max_jobs is not None and args.max_jobs < 1:
        p.error("--max-jobs must be >= 1")

    try:
        sort_spec = parse_sort_spec(args.sort)
    except ValueError as exc:
        p.error(str(exc))

    roles_dir = PROJECT_ROOT / "roles"
    if not roles_dir.is_dir():
        print(f"Error: roles directory not found: {roles_dir}", file=sys.stderr)
        return 1

    lifecycles = parse_lifecycles(args.lifecycles)

    if args.variant:
        rows = compute_variant_complexity_rows(
            roles_dir,
            include_group_names=not args.no_group_names,
            max_level=args.level,
            lifecycles=lifecycles,
        )
    else:
        rows = compute_complexity_rows(
            roles_dir,
            include_group_names=not args.no_group_names,
            max_level=args.level,
            deploy_mode=args.deploy_mode,
            lifecycles=lifecycles,
        )

    _apply_sort(rows, sort_spec)
    rows = _mark_covered(rows)
    _apply_sort(rows, sort_spec)

    if args.filter:
        try:
            predicate = compile_predicate(args.filter, FILTER_FIELDS)
        except FilterError as exc:
            p.error(f"--filter: {exc}")
        rows = [r for r in rows if predicate(_row_fields(r))]

    numbered: list[ComplexityRow] = []
    running = 0
    for line, r in enumerate(rows, start=1):
        running += r.bundles
        numbered.append(r._replace(row=line, jobs=running))
    rows = numbered

    if args.max_jobs is not None:
        rows = [r for r in rows if r.jobs < args.max_jobs]

    if args.format == "json":
        rendered = render_json(rows)
    elif args.format == "yaml":
        rendered = render_yaml(rows)
    elif args.format == "string":
        rendered = render_string(rows)
    else:
        rendered = render_table(rows, symbol=args.symbol)
    if rendered:
        print(rendered)
    return 0
