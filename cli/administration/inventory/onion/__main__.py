#!/usr/bin/env python3
"""CLI: pre-mint the node Tor v3 onion identity (key files) and print its address."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.administration.inventory.onion import ensure_node_onion


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-mint the node Tor v3 onion identity for an onion deploy."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    env_parser = sub.add_parser(
        "init-env",
        help="Mint (or reuse) the node onion key files and print the .onion address.",
    )
    env_parser.add_argument("--env-file", default=".env")

    args = parser.parse_args()
    if args.command == "init-env":
        print(ensure_node_onion(Path(args.env_file).parent))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
