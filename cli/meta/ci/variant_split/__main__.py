"""Verify that a variant split keeps the coverage of the row it shortens."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from utils.cache.files import read_text

from . import compare, cost, segments, snapshot

DEFAULT_SWEEPS = "0,1,2,3,4,5"


def _load(path: str) -> dict:
    return json.loads(read_text(path))


def _tokens(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="infinito meta ci variant_split",
        description=(
            "Check a variant split against the CI matrix the repository really "
            "plans: 'snapshot' records the rows, rounds, edges, axes and budget "
            "of the current tree under one CI run's discovery seed; 'compare' "
            "diffs a snapshot taken before the split with one taken after it, "
            "edge by edge, pin-aware coverage credit by credit and axis pair by "
            "axis pair over the sweeps; 'segments' measures one row's per-app "
            "time on one runner and 'merge' joins measurements of one runner; "
            "'cost' turns them into the per-row saving and the net runner-time "
            "delta. Nothing is deployed or written outside --out."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Record the current tree's matrix.")
    snap.add_argument("--out", required=True, help="JSON file to write.")
    snap.add_argument(
        "--seed",
        required=True,
        help="Discovery seed: the CI run id, as CI sets INFINITO_DISCOVERY_SEED.",
    )
    snap.add_argument(
        "--sweeps", default=DEFAULT_SWEEPS, help="Comma-separated sweep numbers."
    )
    cmp_ = sub.add_parser("compare", help="Diff a before and an after snapshot.")
    cmp_.add_argument("before", help="Snapshot of the tree without the split.")
    cmp_.add_argument("after", help="Snapshot of the tree with the split.")
    cmp_.add_argument(
        "--old", required=True, help="Comma-separated tokens the split replaces."
    )
    cmp_.add_argument(
        "--split", required=True, help="Comma-separated tokens that carry them now."
    )
    cmp_.add_argument("--out", default=None, help="Write the verdict JSON here too.")
    cst = sub.add_parser("cost", help="Per-row saving and net runner-time delta.")
    cst.add_argument("before", help="Snapshot of the tree without the split.")
    cst.add_argument("after", help="Snapshot of the tree with the split.")
    cst.add_argument("--segments", required=True, help="Measured per-app segment JSON.")
    cst.add_argument("--old", required=True, help="Comma-separated replaced tokens.")
    cst.add_argument("--split", required=True, help="Comma-separated carrying tokens.")
    seg = sub.add_parser("segments", help="Per-app segments of one measured row.")
    seg.add_argument("snapshot", help="Snapshot whose round of --row is measured.")
    seg.add_argument("--row", required=True, help="The measured row's token.")
    seg.add_argument(
        "--runner",
        required=True,
        help="The runner the measured job ran on; merge joins one runner only.",
    )
    seg.add_argument(
        "--pass",
        dest="passes",
        action="append",
        required=True,
        metavar="N=TSV|N=FIRST:LAST",
        help=(
            "Pass number and its per-task wall TSV, or with --log its line "
            "range from the PASS marker (LAST empty: end of log); repeat per pass."
        ),
    )
    seg.add_argument(
        "--log",
        default=None,
        help="Raw deploy log to segment by first task per app; prints aggregates only.",
    )
    seg.add_argument("--cut", default="", help="Comma-separated passes that were cut.")
    seg.add_argument("--out", required=True, help="Segments JSON to write.")
    mrg = sub.add_parser("merge", help="Join segments files of one runner.")
    mrg.add_argument(
        "files", nargs="+", help="Segments files, the primary first; one runner."
    )
    mrg.add_argument("--out", required=True, help="Merged segments JSON to write.")
    return p


def _span(span: str) -> tuple[int, int | None]:
    first, _, last = span.partition(":")
    return int(first), int(last) if last else None


def _segments(args: argparse.Namespace) -> int:
    from utils.roles.entity.name import entity_name

    record = _load(args.snapshot)["rounds"][args.row]
    passes = dict(item.split("=", 1) for item in args.passes)
    source = f"{args.row}: " + ", ".join(
        f"pass {n} {p}" for n, p in sorted(passes.items())
    )
    if args.log:
        data = segments.build_from_log(
            read_text(args.log).splitlines(),
            {number: _span(span) for number, span in passes.items()},
            list(record["include"]),
            runner=args.runner,
            cut=_tokens(args.cut),
            source=f"{Path(args.log).name} {source}",
        )
    else:
        data = segments.build(
            {number: read_text(path) for number, path in passes.items()},
            list(record["include"]),
            entity_of=entity_name,
            runner=args.runner,
            cut=_tokens(args.cut),
            source=source,
        )
    Path(args.out).write_text(json.dumps(data, sort_keys=True))
    for number in sorted(data["passes"]):
        top = sorted(data["passes"][number].items(), key=lambda kv: -kv[1])[:8]
        print(
            f"pass {number}: total {data['measured_total'][number]}s, fixed "
            f"{data['measured_fixed'][number]}s, top apps {top}"
        )
    return 0


def _merge(args: argparse.Namespace) -> int:
    data = segments.merge([_load(path) for path in args.files])
    Path(args.out).write_text(json.dumps(data, sort_keys=True))
    priced = {number: len(apps) for number, apps in sorted(data["passes"].items())}
    print(
        f"runner {data['runner']}: apps priced per pass {priced}, lower bound "
        f"{data['lower_bound']} -> {args.out}"
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.command == "snapshot":
        data = snapshot.take([int(s) for s in _tokens(args.sweeps)], seed=args.seed)
        Path(args.out).write_text(json.dumps(data, sort_keys=True))
        print(
            f"{len(data['rows'])} rows, {len(data['rounds'])} rounds, sweeps "
            f"{sorted(data['sweeps'])}, budget {data['budget']['available']}, "
            f"seed {data['seed']} -> {args.out}"
        )
        return 0
    if args.command == "segments":
        return _segments(args)
    if args.command == "merge":
        return _merge(args)
    before, after = _load(args.before), _load(args.after)
    snapshot.check_seeds(before, after)
    old, split = _tokens(args.old), _tokens(args.split)
    if args.command == "compare":
        verdict = compare.verdict(before, after, old=old, split=split)
        print(compare.render(verdict))
        if args.out:
            Path(args.out).write_text(json.dumps(verdict, sort_keys=True, default=list))
        return 0 if verdict["kept"] else 1
    result = cost.delta(before, after, _load(args.segments), old=old, split=split)
    print(cost.render(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
