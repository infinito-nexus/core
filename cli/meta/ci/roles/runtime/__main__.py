from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .render import FORMATS, render
from .sources import load_records


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.ci.roles.runtime",
        description=(
            "Summarise Ansible profile_roles runtimes per matrix-deploy "
            "variant. SOURCE is an Ansible run log, a role-runtimes CSV, or a "
            "GitHub Actions run/job URL (CSV artifacts are downloaded via gh)."
        ),
    )
    p.add_argument(
        "source",
        help="Ansible log path, role-runtimes CSV path, or GitHub Actions run/job URL.",
    )
    p.add_argument(
        "--format",
        choices=FORMATS,
        default="table",
        help="Output format (default: table).",
    )
    p.add_argument(
        "--output",
        help="Write to this file instead of stdout.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        records = load_records(args.source)
    except FileNotFoundError as exc:
        print(f"[role-runtime] source not found: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[role-runtime] failed to load {args.source}: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("[role-runtime] no profile_roles entries found", file=sys.stderr)
        return 1

    text = render(records, args.format)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
