from __future__ import annotations

import argparse
import json

from . import PROJECT_ROOT, detect_runtime


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.runtime",
        description="Detect and print the current Infinito runtime environment.",
    )

    p.add_argument(
        "--print-root",
        action="store_true",
        help="Also print the detected project root.",
    )

    p.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON object.",
    )

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    runtime = detect_runtime()

    if args.json:
        payload = {
            "runtime": runtime,
            "project_root": str(PROJECT_ROOT),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(runtime)
        if args.print_root:
            print(f"project_root={PROJECT_ROOT}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
