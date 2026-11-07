"""Print the variant tree of one CI row as text, JSON or YAML."""

from __future__ import annotations

import argparse
import json
import sys

from utils.cache.yaml import dump_yaml_str

from . import tree


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="infinito meta ci variant_tree",
        description=(
            "Print the variant tree one CI row really deploys: the primary "
            "role#variant, every dependency with the variant its round settles "
            "on and why (round index, a variant pin in force, or default 0), "
            "each node's services and their state (required, presence-gated, "
            "forced by override, implicit, off), the closure size as the "
            "resolve_round include count, and the axes the job list assigns "
            "the row per sweep. Reads the tree, deploys nothing."
        ),
    )
    p.add_argument(
        "row", metavar="ROLE#VARIANT", help="The row, e.g. web-app-wordpress#0."
    )
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="Print JSON.")
    fmt.add_argument("--yaml", action="store_true", help="Print YAML.")
    p.add_argument(
        "--sweeps",
        default="0",
        help="Comma-separated sweeps to assign axes for; empty skips the axes.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from cli.meta.ci.variant_split.snapshot import row_axes
    from utils.cache.applications import get_variants
    from utils.cache.files import PROJECT_ROOT

    roles_dir = str(PROJECT_ROOT / "roles")
    try:
        data = tree.build(
            args.row,
            roles_dir=roles_dir,
            variants_per_app=get_variants(roles_dir=roles_dir, readonly=True),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sweeps = [int(s) for s in args.sweeps.split(",") if s.strip()]
    if sweeps and not data.get("error"):
        data["axes"] = row_axes(data["primary"], sweeps)
    if args.json:
        print(json.dumps(data, indent=2))
    elif args.yaml:
        print(dump_yaml_str(data), end="")
    else:
        print(tree.render_text(data))
    return 1 if data.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
