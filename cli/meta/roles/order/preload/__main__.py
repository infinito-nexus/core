#!/usr/bin/env python3
"""
What it does:
- 📄 Prints the sys-service-loader preload order: every primary shared
  service from the registry, topologically sorted by run_after
  (bucket-agnostic), bucket + name as tie-break among ready roles
- 🔎 Shows per entry: position, service id, role, and its run_after edges
- 🧷 This is the loader-pass order (tasks/stages/01_constructor.yml);
  for the group-file main pass use cli.meta.roles.order.run

Examples:
  # 1) Print the full preload order
  python -m cli.meta.roles.order.preload

  # 2) Filter to roles matching a substring
  python -m cli.meta.roles.order.preload --grep bkp
"""

from __future__ import annotations

import argparse

from utils import PROJECT_ROOT
from utils.roles.applications.services.registry import (
    ServiceRegistryError,
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
)
from utils.roles.meta_lookup import get_role_run_after


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.order.preload",
        description="Print the sys-service-loader preload order (run_after topological sort).",
    )
    ap.add_argument(
        "--grep",
        help="Only show entries whose role or service id contains this substring.",
        default=None,
    )
    args = ap.parse_args(argv)

    roles_dir = PROJECT_ROOT / "roles"
    try:
        registry = build_service_registry_from_roles_dir(roles_dir)
        ordered = ordered_primary_service_entries(registry, roles_dir)
    except ServiceRegistryError as exc:
        print(f"❌ {exc}")
        return 1

    shown = 0
    for pos, entry in enumerate(ordered, start=1):
        role = entry["role"]
        service_id = entry["id"]
        if args.grep and args.grep not in role and args.grep not in service_id:
            continue
        shown += 1
        run_after = get_role_run_after(roles_dir / role, role_name=role)
        suffix = f"  (run_after: {', '.join(run_after)})" if run_after else ""
        print(f"{pos:3d}. {service_id:<24} {role}{suffix}")

    if not shown:
        print(f"ℹ️  No preload entries match {args.grep!r}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
