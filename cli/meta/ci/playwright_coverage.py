"""Report which sweep row first triggers each Playwright spec.

The classification lives in :mod:`utils.roles.playwright_coverage`, shared
with the integration test that holds the line; this renders it.
"""

from __future__ import annotations

import argparse
import sys

from cli.meta.ci import matrix, query
from cli.meta.roles.applications.complexity.render import _dwidth
from utils import PROJECT_ROOT
from utils.github.variant import axes, network, pools, vpn
from utils.roles.display import display_names
from utils.roles.playwright_coverage import (
    Coverage,
    chunk_index,
    classify,
    first_rows,
    specs_by_role,
)

_HEADERS = ("Role", "Spec", "Variant", "Mode", "Chunk")


def sweep_entries(args: argparse.Namespace) -> list[dict[str, str]]:
    codec = display_names()
    return matrix.entries_of(
        modes=query.resolve_modes(args.modes),
        whitelist=codec.decode_list(""),
        priority=codec.decode_list(""),
        lifecycles="",
        sweep=axes.resolve_sweep() if args.sweep is None else args.sweep,
        network_input=network.resolve_network_input(args.network),
        vpn_mode=vpn.resolve_vpn_mode(args.vpn),
        distros=pools.resolve_distros(args.distros),
        filesystems=pools.resolve_filesystems(args.filesystem),
        architectures=pools.resolve_architectures(args.architectures),
    )


def render(coverage: Coverage) -> str:
    rows = [tuple(row) for row in coverage.triggered]
    widths = [
        max(_dwidth(cell) for cell in column)
        for column in zip(_HEADERS, *rows, strict=False)
    ]

    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(
            cell + " " * (width - _dwidth(cell))
            for cell, width in zip(cells, widths, strict=True)
        )

    lines = [line(_HEADERS), "  ".join("-" * width for width in widths)]
    lines.extend(line(row) for row in rows)
    total = len(rows) + len(coverage.uncovered) + len(coverage.excluded)
    lines.append("")
    lines.append(
        f"specs: {total}, triggered: {len(rows)}, "
        f"never triggered: {len(coverage.uncovered)}, "
        f"outside the tested lifecycles: {len(coverage.excluded)}"
    )
    lines.extend(
        f"  never triggered: {role}: {spec}" for role, spec in coverage.uncovered
    )
    lines.extend(
        f"  lifecycle {entry.lifecycle}: {entry.role}: {entry.spec}"
        for entry in coverage.excluded
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show the first row that triggers each Playwright spec."
    )
    parser.add_argument("--distros", default="")
    parser.add_argument("--modes", default=query.ALL_MODES)
    parser.add_argument("--sweep", type=int, default=None)
    parser.add_argument("--network", default=None)
    parser.add_argument("--vpn", default=None)
    parser.add_argument("--filesystem", default="")
    parser.add_argument("--architectures", default="")
    parser.add_argument("--offset", default=None)
    args = parser.parse_args(argv)

    entries = sweep_entries(args)
    plan = matrix.chunks_of(entries, matrix.resolve_offset(args.offset))
    roles_dir = PROJECT_ROOT / "roles"
    coverage = classify(
        specs_by_role(roles_dir), first_rows(entries), chunk_index(plan), roles_dir
    )
    print(render(coverage))
    return 1 if coverage.uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
