#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

# Ensure repo root is in PYTHONPATH
from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from utils.roles.validation.resources import filter_roles_by_min_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate roles by services.<entity>.min_storage in roles/*/meta/services.yml"  # nocheck: role-file-spot
        )
    )

    parser.add_argument(
        "--roles",
        nargs="+",
        required=True,
        help="List of role names (directory names under roles/)",
    )

    parser.add_argument(
        "--required-storage",
        required=True,
        help="Required storage value (e.g. 80G, 1Ti, 500GB, 2 TB)",
    )

    parser.add_argument(
        "--warnings",
        action="store_true",
        help="Emit GitHub Actions warnings for invalid min_storage metadata on matching compose services",
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text). text = one role per line; json = JSON array.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    matching = filter_roles_by_min_storage(
        role_names=args.roles,
        required_storage=args.required_storage,
        emit_warnings=args.warnings,
    )

    if args.format == "json":
        # Always output valid JSON
        print(json.dumps(matching, indent=2))
        return 0

    # text: one role per line (robust for shell pipelines)
    for role in matching:
        print(role)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
