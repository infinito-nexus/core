#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from . import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import utils.domains.list as domain_list


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List rendered canonical domains and aliases from role configs."
    )
    parser.add_argument(
        "--domain-primary",
        default=os.environ.get("DOMAIN", "infinito.test"),
        help="Value used for DOMAIN_PRIMARY rendering",
    )
    parser.add_argument(
        "--alias",
        dest="include_aliases",
        action="store_true",
        help="Include alias domains from role configs",
    )
    parser.add_argument(
        "--www",
        dest="include_www",
        action="store_true",
        help="Add www. variants for each non-www domain",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roles_dir = domain_list.ROLES_DIR.resolve()
    if not roles_dir.is_dir():
        print(f"Roles directory not found: {roles_dir}", file=sys.stderr)
        return 1

    for domain in domain_list.list_application_domains(
        args.domain_primary,
        include_aliases=args.include_aliases,
        include_www=args.include_www,
    ):
        print(domain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
