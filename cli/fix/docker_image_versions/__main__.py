#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from utils.docker.version_updater import apply_updates, find_outdated_updates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update semver-based Docker image versions in web-*/meta/services.yml."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
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
        print("Docker image versions are already up to date.")
        return 0

    print("Planned Docker image updates:")
    for update in updates:
        rel_path = update.entry.config_path.relative_to(repo_root)
        print(
            f"- {rel_path}:{update.entry.service} "
            f"{update.entry.image} {update.entry.version} -> {update.latest}"
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
