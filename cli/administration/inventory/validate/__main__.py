#!/usr/bin/env python3
"""Inventory validator orchestration: load → compare → report."""

import argparse
import sys
from pathlib import Path

# nocheck: project-root-import  sys.path bootstrap before package imports resolve
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cli.administration.inventory.validate.applications import (  # noqa: E402
    compare_application_keys,
)
from cli.administration.inventory.validate.hosts import validate_host_keys  # noqa: E402
from cli.administration.inventory.validate.loaders import (  # noqa: E402
    load_inventory_files,
    load_yaml_file,
)
from cli.administration.inventory.validate.users import compare_user_keys  # noqa: E402
from utils.cache.applications import (  # noqa: E402
    get_application_defaults,
    get_variants,
)
from utils.cache.users import get_user_defaults  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("inventory_dir")
    p.add_argument(
        "--roles-dir",
        default=str(PROJECT_ROOT / "roles"),
        help="Path to the repository roles directory.",
    )
    args = p.parse_args()

    application_defaults = get_application_defaults(roles_dir=args.roles_dir)
    variants = get_variants(roles_dir=args.roles_dir)
    user_defaults = get_user_defaults(roles_dir=args.roles_dir)
    if not application_defaults:
        print(
            "Error: No application defaults discovered in roles directory",
            file=sys.stderr,
        )
        sys.exit(1)
    if not user_defaults:
        print("Error: No user defaults discovered in roles directory", file=sys.stderr)
        sys.exit(1)

    app_errs: list[str] = []
    inv_files = load_inventory_files(args.inventory_dir)
    for src, apps in inv_files.items():
        app_errs.extend(
            compare_application_keys(apps, application_defaults, src, variants)
        )

    user_errs: list[str] = []
    for fpath in Path(args.inventory_dir).rglob("*.yml"):
        data = load_yaml_file(fpath)
        if isinstance(data, dict) and "users" in data:
            errs = compare_user_keys(data["users"], user_defaults, str(fpath))
            for e in errs:
                print(e, file=sys.stderr)
            user_errs.extend(errs)

    host_errs = validate_host_keys(set(application_defaults), args.inventory_dir)
    app_errs.extend(host_errs)

    if app_errs or user_errs:
        if app_errs:
            print("Validation failed with the following issues:")
            for e in app_errs:
                print(f"- {e}")
        sys.exit(1)
    print("Inventory directory is valid against defaults and hosts.")
    sys.exit(0)


if __name__ == "__main__":
    main()
