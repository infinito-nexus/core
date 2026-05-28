"""
Resolve and aggregate role groups (apps) from one or more inventory bundles.

Bundles live under ``inventories/bundles/{servers,workstations}/<name>/inventory.yml``.
Each bundle declares the role groups it activates beneath ``all.children``.

Invoked from ``scripts/tests/deploy/local/deploy/bundles/fresh.sh`` to feed the `apps` env var into
the existing fresh-purged deploy flow:

    python -m utils.inventory.bundle_apps education-suite,startup-essentials
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

SEARCH_DIRS = (
    PROJECT_ROOT / "inventories" / "bundles" / "servers",
    PROJECT_ROOT / "inventories" / "bundles" / "workstations",
)


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _locate(bundle: str) -> Path | None:
    for base in SEARCH_DIRS:
        candidate = base / bundle / "inventory.yml"
        if candidate.is_file():
            return candidate
    return None


def resolve(bundles: Iterable[str]) -> list[str]:
    """Return deduplicated role-group names from the given bundle inventories.

    Raises FileNotFoundError if any bundle is missing.
    """
    apps: list[str] = []
    seen: set[str] = set()
    missing: list[str] = []

    for bundle in bundles:
        inventory = _locate(bundle)
        if inventory is None:
            missing.append(bundle)
            continue
        data = load_yaml(inventory, default_if_missing={}) or {}
        children = (data.get("all") or {}).get("children") or {}
        for app in children:
            if app in seen:
                continue
            seen.add(app)
            apps.append(app)

    if missing:
        raise FileNotFoundError(
            "bundle(s) not found under inventories/bundles/"
            "{servers,workstations}: " + ", ".join(missing)
        )

    return apps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utils.inventory.bundle_apps",
        description="Aggregate role groups from inventory bundles into a CSV.",
    )
    parser.add_argument(
        "bundles",
        help="Comma-separated bundle names (e.g. education-suite,startup-essentials).",
    )
    args = parser.parse_args(argv)

    names = _split_csv(args.bundles)
    if not names:
        sys.stderr.write("ERROR: no bundle names provided\n")
        return 2

    try:
        apps = resolve(names)
    except FileNotFoundError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    if not apps:
        sys.stderr.write("ERROR: no role groups resolved from bundles\n")
        return 2

    sys.stdout.write(",".join(apps) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
