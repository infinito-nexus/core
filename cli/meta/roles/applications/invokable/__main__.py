#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from utils.roles.validation.invokable import list_invokable_app_ids


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List all invokable applications (application_ids) based on invokable paths from categories.yml and available roles."
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    try:
        result = list_invokable_app_ids()
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(result, indent=2))
        return

    for app_id in result:
        print(app_id)


if __name__ == "__main__":
    main()
