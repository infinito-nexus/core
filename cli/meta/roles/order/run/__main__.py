#!/usr/bin/env python3
"""
Group-agnostic role call order.

- 🧷 Phase 1 (preload): every primary shared service from the registry,
  topologically sorted by run_after (the sys-service-loader pass, identical
  to ``cli.meta.roles.order.preload``).
- 📦 Phase 2 (main): every remaining invokable role that is NOT a preload
  service, topologically sorted by run_after among themselves. Roles that
  become ready together fall out in stage order (constructor -> workstation
  -> server -> destructor) via ``roles/categories.yml``, then category
  run_after, then name.

Derived purely from ``meta/*.yml`` (run_after + the service registry) and
``roles/categories.yml`` (stage), NOT from ``tasks/stages/*.yml``, so it
stays independent of how the stage playbooks happen to be split.

Examples:
  # 1) Full call order, both phases
  python -m cli.meta.roles.order.run

  # 2) Only entries whose role id matches a substring
  python -m cli.meta.roles.order.run --grep backup

  # 3) Split the order at a marker role (called <= marker vs remaining)
  python -m cli.meta.roles.order.run --marker web-app-nextcloud
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.roles.applications.services.registry import (
    ServiceRegistryError,
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
    run_after_topological_order,
)
from utils.roles.meta_lookup import get_role_run_after
from utils.roles.stage import role_sort_key
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
)

if TYPE_CHECKING:
    from pathlib import Path


def _invokable_role_dirs(roles_dir: Path) -> list[str]:
    """Role directory names that are invokable (the deployable universe)."""
    paths = _get_invokable_paths()
    return sorted(
        p.name
        for p in roles_dir.iterdir()
        if p.is_dir() and _is_role_invokable(p.name, paths)
    )


def build_call_order(roles_dir: Path) -> list[tuple[str, str]]:
    """(phase, role) for every deployed role: preload phase first (registry
    run_after order), then the main phase (remaining invokable roles in
    run_after topological order)."""
    registry = build_service_registry_from_roles_dir(roles_dir)
    preload = [
        entry["role"] for entry in ordered_primary_service_entries(registry, roles_dir)
    ]
    preload_set = set(preload)

    main_nodes = [r for r in _invokable_role_dirs(roles_dir) if r not in preload_set]
    main = run_after_topological_order(
        main_nodes,
        lambda r: get_role_run_after(roles_dir / r, role_name=r),
        role_sort_key,
    )

    return [("preload", r) for r in preload] + [("main", r) for r in main]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.order.run",
        description="Group-agnostic role call order: preload services first, then the remaining invokable roles (run_after topological order).",
    )
    ap.add_argument(
        "--grep",
        help="Only show entries whose role id contains this substring.",
        default=None,
    )
    ap.add_argument(
        "--marker",
        help="Split the order at this role: entries at/before it are 'called', the rest 'remaining'.",
        default=None,
    )
    args = ap.parse_args(argv)

    roles_dir = PROJECT_ROOT / "roles"
    try:
        order = build_call_order(roles_dir)
    except ServiceRegistryError as exc:
        print(f"❌ {exc}")
        return 1

    marker = (args.marker or "").strip() or None
    marker_pos = next((i for i, (_p, r) in enumerate(order) if r == marker), None)
    if marker and marker_pos is None:
        print(f"⚠️  Marker role not found: {marker!r}")

    def render(pos: int, phase: str, role: str) -> str:
        icon = "🧷" if phase == "preload" else "📦"
        run_after = get_role_run_after(roles_dir / role, role_name=role)
        suffix = f"  (run_after: {', '.join(run_after)})" if run_after else ""
        mark = " 🎯" if role == marker else ""
        return f"{pos:3d}. {icon} {role}{mark}{suffix}"

    shown = 0
    last_split = None
    for pos, (phase, role) in enumerate(order, start=1):
        if args.grep and args.grep not in role:
            continue
        if marker_pos is not None:
            split = (
                "✅ called (<= marker)"
                if pos - 1 <= marker_pos
                else "⏳ remaining (> marker)"
            )
            if split != last_split:
                print(f"\n{split}")
                last_split = split
        print(render(pos, phase, role))
        shown += 1

    if not shown:
        print(f"ℹ️  No entries match {args.grep!r}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
