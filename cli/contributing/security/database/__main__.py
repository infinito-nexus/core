#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from utils.security.database import fetch_databases, fetch_url
from utils.security.engine import SCANNERS
from utils.security.pipeline import pipeline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Download the vulnerability databases a CI deploy reads."
    )
    parser.add_argument(
        "--dir", required=True, help="Database root, one directory per engine"
    )
    parser.add_argument(
        "--engines",
        required=True,
        nargs="+",
        choices=SCANNERS,
        help="Databases to download",
    )
    args = parser.parse_args(argv)
    p = pipeline()
    errors = fetch_databases(
        p, Path(args.dir).resolve(), args.engines, p.default_runner, fetch_url
    )
    for error in errors:
        print(f"❌ {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
