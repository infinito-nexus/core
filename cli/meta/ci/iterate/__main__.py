"""Plan what an iteration on a diff has to run, so no relevant role, mode or
test is skipped.

Usage:
  python -m cli.meta.ci.iterate [--base <ref>] [--head <ref>] [--loop auto]
      [--disable <keys>|none] [--timings <log|csv>] [--format json]

Every changed path is classified (a role path seeds its role, a format-only
edit reaches nothing, a shared plugin, module or group_vars key reaches the
roles the symbol index finds consuming it, an unknown path widens to the full
set), then the tiers are planned: T0 the unit and lint commands of the diff,
T1 the inner-loop rows, T2 the pre-push rows and gate, T3 the CI whitelist.
``cuts`` names everything a tier leaves out and why, the narrowing against
``affected_roles.sh`` included. The symbol index and the resolver read the
current tree, also when ``--head`` names an older commit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from cli.meta.ci.iterate import diff
from cli.meta.ci.iterate.catalog import Catalog
from cli.meta.ci.iterate.classify import classify
from cli.meta.ci.iterate.plan import LOOPS, build
from cli.meta.ci.iterate.render import render
from cli.meta.ci.iterate.symbols import Index
from utils.cache.files import PROJECT_ROOT


def plan_span(
    span: diff.Span, catalog: Catalog, *, loop: str, disable: str, timings: str
) -> dict:
    """Return the plan of one span, with its sides and its wall time.

    Args:
        span: the diff.
        catalog: the roles tree facts.
        loop: as :func:`cli.meta.ci.iterate.plan.build` takes it.
        disable: as :func:`cli.meta.ci.iterate.plan.build` takes it.
        timings: as :func:`cli.meta.ci.iterate.plan.build` takes it.
    """
    started = time.monotonic()
    paths = diff.changed_paths(span)
    index = Index(PROJECT_ROOT)

    def read(path: str) -> tuple[str | None, str | None]:
        return diff.content(span.base, path), diff.content(span.head, path)

    changes = [classify(path, read, index, catalog.exists) for path in paths]
    result = build(paths, changes, catalog, loop=loop, disable=disable, timings=timings)
    return {
        "base": span.base,
        "head": span.head,
        **result,
        "elapsed_s": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plan what an iteration on a diff has to run: the unit and lint "
            "commands (T0), the inner-loop rows (T1), the pre-push rows (T2) "
            "and the CI whitelist (T3), with every cut named."
        )
    )
    parser.add_argument(
        "--base",
        default="",
        help="ref the diff starts from (merge base of origin/main)",
    )
    parser.add_argument(
        "--head", default="", help="ref the diff ends at (the working tree)"
    )
    parser.add_argument("--loop", default="", choices=("", *LOOPS))
    parser.add_argument(
        "--disable",
        default="",
        help="provider keys rendered disabled; empty proposes the compose default, none disables nothing",
    )
    parser.add_argument(
        "--timings",
        default="",
        help="deploy log or role-runtimes CSV that prices the rows (declared storage)",
    )
    parser.add_argument("--format", default="", choices=("", "json"))
    args = parser.parse_args(argv)
    result = plan_span(
        diff.resolve(args.base, args.head),
        Catalog(),
        loop=args.loop,
        disable=args.disable,
        timings=args.timings,
    )
    print(json.dumps(result, indent=2) if args.format == "json" else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
