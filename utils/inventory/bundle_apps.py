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
from typing import TYPE_CHECKING, Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

SEARCH_DIRS = (
    PROJECT_ROOT / "inventories" / "bundles" / "servers",
    PROJECT_ROOT / "inventories" / "bundles" / "workstations",
)
CATALOG_KEY = "infinito"


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _locate(bundle: str) -> Path | None:
    for base in SEARCH_DIRS:
        candidate = base / bundle / "inventory.yml"
        if candidate.is_file():
            return candidate
    return None


def _all_groups(bundles: Iterable[str]) -> list[dict[str, Any]]:
    """Return the ``all`` group of every named bundle inventory, in order.

    Args:
        bundles: bundle names.

    Returns:
        One mapping per bundle, empty when the inventory has no ``all`` group.

    Raises:
        FileNotFoundError: one or more bundles are missing; all are named.
    """
    groups: list[dict[str, Any]] = []
    missing: list[str] = []

    for bundle in bundles:
        inventory = _locate(bundle)
        if inventory is None:
            missing.append(bundle)
            continue
        data = load_yaml(inventory, default_if_missing={}) or {}
        groups.append(data.get("all") or {})

    if missing:
        raise FileNotFoundError(
            "bundle(s) not found under inventories/bundles/"
            "{servers,workstations}: " + ", ".join(missing)
        )

    return groups


def resolve(bundles: Iterable[str]) -> list[str]:
    """Return deduplicated role-group names from the given bundle inventories.

    Raises FileNotFoundError if any bundle is missing.
    """
    apps: list[str] = []
    seen: set[str] = set()

    for group in _all_groups(bundles):
        for app in group.get("children") or {}:
            if app in seen:
                continue
            seen.add(app)
            apps.append(app)

    return apps


def resolve_vars(bundles: Iterable[str]) -> dict[str, Any]:
    """Return the ``all.vars`` of the given bundle inventories a deploy reads.

    Args:
        bundles: bundle names, merged in order; a later bundle wins per
            top-level key, as with several ``-i`` sources in Ansible.

    Returns:
        The merged vars without ``CATALOG_KEY``; empty when no bundle
        declares any other var.

    Raises:
        FileNotFoundError: one or more bundles are missing; all are named.
    """
    merged: dict[str, Any] = {}
    for group in _all_groups(bundles):
        merged.update(group.get("vars") or {})
    merged.pop(CATALOG_KEY, None)
    return merged


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
