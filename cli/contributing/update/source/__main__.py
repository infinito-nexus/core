#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from utils.update.source import apply_updates, find_outdated_updates

from . import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Update version pins that declare their upstream in an `update:` "
            "block of roles/*/meta/services.yml."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Repository root to scan and update",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned updates without modifying files",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    updates = find_outdated_updates(repo_root)

    if not updates:
        print("Declared version sources are already up to date.")
        return 0

    print("Planned version source updates:")
    for update in updates:
        entry = update.entry
        rel_path = entry.config_path.relative_to(repo_root)
        print(
            f"- {rel_path}:{entry.line} {entry.role}/{entry.entity}.{entry.key} "
            f"{entry.current} -> {update.latest}"
        )

    if args.dry_run:
        return 0

    changed_paths = apply_updates(updates)
    if changed_paths:
        print("\nUpdated files:")
        for path in changed_paths:
            print(f"- {path.relative_to(repo_root)}")
    else:
        print("\nNo files changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
