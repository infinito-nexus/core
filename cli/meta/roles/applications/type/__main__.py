#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from utils.roles.validation.invokable import list_invokables_by_type


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List invokable applications grouped by deployment type (server/workstation/universal)."
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=("server", "workstation", "universal"),
        help="Return only the list for a single deployment type",
    )
    parser.add_argument(
        "--lifecycles",
        nargs="+",
        help="Optional lifecycle filter (space-separated), e.g. alpha beta rc stable. "
        "If omitted, no lifecycle filtering is applied (all roles are returned).",
    )
    parser.add_argument(
        "--skip-mode",
        choices=("compose", "swarm"),
        help="Exclude roles whose meta/services.yml skip list contains this "
        "deployment mode (test-deploy discovery opt-out).",
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
        lifecycles = None
        if args.lifecycles:
            lifecycles = {
                str(x).strip().lower() for x in args.lifecycles if str(x).strip()
            }
        grouped = list_invokables_by_type(
            lifecycles=lifecycles, skip_mode=args.skip_mode
        )
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

    if args.type:
        apps = grouped.get(args.type, [])
        if args.format == "json":
            print(json.dumps(apps, indent=2))
            return
        for app_id in apps:
            print(app_id)
        return

    if args.format == "json":
        print(json.dumps(grouped, indent=2, sort_keys=True))
        return

    # text
    for t in ("server", "workstation", "universal"):
        apps = grouped.get(t, [])
        print(f"[{t}]")
        for app_id in apps:
            print(app_id)
        print()


if __name__ == "__main__":
    main()
