#!/usr/bin/env python3
"""CLI: pre-mint the node Tor v3 onion identity into the env file + key files."""

from __future__ import annotations

import argparse
import sys

from cli.administration.inventory.onion import init_env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-mint the node Tor v3 onion identity for an onion deploy."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    env_parser = sub.add_parser(
        "init-env",
        help="Mint a node onion and write INFINITO_DOMAIN(+_RE) + key files.",
    )
    env_parser.add_argument("--env-file", default=".env")

    args = parser.parse_args()
    if args.command == "init-env":
        print(init_env(args.env_file))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
