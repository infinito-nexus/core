from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING

from cli import PROJECT_ROOT

from . import (
    STATE_CURRENT,
    STATE_REVIEW,
    GitError,
    build_queue,
    collect_facts,
    not_due,
    repository_root,
)

if TYPE_CHECKING:
    from . import QueueEntry

_COLUMNS = ("rank", "role", "state", "reason")

_DESCRIPTION = """\
Print the web UI roles that need a corporate-design pass, in working order.

states:
  new      HEAD carries no design spec for the role; newest role first
  stale    image version or shared design base moved since the last design
           pass; largest version gap first, a base-only change last
  review   the design spec is uncommitted and awaits approval; not due
  current  nothing moved since the last design pass; not due
"""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.design",
        description=_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--next",
        action="store_true",
        help="Print only the role name of rank 1, nothing when no role is due.",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Also list the review and current roles after the due queue.",
    )
    p.add_argument(
        "--format",
        choices=("text", "json"),
        help="Output format, the aligned text table when omitted. json emits a "
        "list of objects with rank, role, state, reason, version_gap, created "
        "and changed; the last two are commit times in Unix epoch seconds.",
    )
    return p


def render_table(rows: list[QueueEntry]) -> str:
    """Render queue entries as an aligned text table.

    Args:
        rows: Entries in output order.

    Returns:
        The header line and one line per entry, columns padded to equal width.
    """
    lines = [
        _COLUMNS,
        *(
            ("" if row.rank is None else str(row.rank), row.role, row.state, row.reason)
            for row in rows
        ),
    ]
    widths = [max(map(len, column)) for column in zip(*lines, strict=True)]
    return "\n".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(line, widths, strict=True)
        ).rstrip()
        for line in lines
    )


def _summary(queue: list[QueueEntry], idle: list[QueueEntry]) -> str:
    review = sum(row.state == STATE_REVIEW for row in idle)
    current = sum(row.state == STATE_CURRENT for row in idle)
    return f"due: {len(queue)}, in review: {review}, current: {current}"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        facts = collect_facts(repository_root(PROJECT_ROOT))
    except GitError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    queue = build_queue(facts)
    if args.next:
        if queue:
            print(queue[0].role)
        return 0

    idle = not_due(facts)
    rows = [*queue, *idle] if args.all else queue
    if args.format == "json":
        print(json.dumps([asdict(row) for row in rows], indent=2))
        return 0

    print(render_table(rows))
    print()
    print(_summary(queue, idle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
