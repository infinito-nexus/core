from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from utils.update import fetch
from utils.update.opentofu import apply_updates, find_outdated_updates, lock_roots

from . import PROJECT_ROOT


def main(argv=None, get=fetch.get, run=subprocess.run) -> int:
    """Args:
        argv: the command line, ``sys.argv[1:]`` when None.
        get: reads an https URL.
        run: runs the lock step's command.

    Returns:
        The exit code.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Update the exact OpenTofu provider pins in roles/*/files/opentofu/ "
            "to the newest registry release and rewrite the lock files."
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
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    updates = find_outdated_updates(repo_root, get)
    if not updates:
        print("OpenTofu provider pins are already up to date.")
        return 0
    print("Planned OpenTofu provider pin updates:")
    for update in updates:
        relative = update.pin.path.relative_to(repo_root)
        print(
            f"- {relative}: {update.pin.source} {update.pin.version} -> {update.latest}"
        )
    if args.dry_run:
        return 0
    changed = apply_updates(updates)
    for root in lock_roots(changed, get, run):
        print(f"- locked {root.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
