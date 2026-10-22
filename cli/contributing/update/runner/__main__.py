#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from utils.update.fetch import document
from utils.update.runner import IMAGES_README, bump_workflows, newest_ubuntu_label

from . import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Raise every workflow's runs-on Ubuntu label to the newest GA "
            "GitHub-hosted x64 image."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Repository root whose .github/workflows are updated",
    )
    args = parser.parse_args()

    label = newest_ubuntu_label(document(IMAGES_README))
    if label is None:
        print(f"No GA x64 Ubuntu label found in {IMAGES_README}.")
        return 1

    repo_root = args.repo_root.resolve()
    changed = bump_workflows(repo_root / ".github" / "workflows", label)
    if not changed:
        print(f"Every workflow already runs on {label} or newer.")
        return 0

    print(f"Raised runs-on to {label} in:")
    for path in changed:
        print(f"- {path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
