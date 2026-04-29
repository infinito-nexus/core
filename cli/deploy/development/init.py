# cli/deploy/development/init.py
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from cli.create.inventory.services_disabler import (
    find_provider_roles,
    parse_services_disabled,
)

from .common import make_compose
from .inventory import (
    DevInventorySpec,
    build_dev_inventory,
    filter_plan_to_variant,
    plan_dev_inventory_matrix,
)
from .storage import detect_storage_constrained
from ...meta.runtime import detect_runtime


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "init",
        help="Create development inventory inside the infinito container.",
    )
    p.add_argument(
        "--inventory-dir",
        default=os.environ.get("INVENTORY_DIR"),
        required=os.environ.get("INVENTORY_DIR") is None,
        help=(
            "Inventory directory base (default: $INVENTORY_DIR). "
            "When the included apps declare more than one matrix-deploy "
            "variant, sibling folders `<dir>-0`, `<dir>-1`, ... are "
            "created; otherwise the directory is used as-is."
        ),
    )

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--apps",
        help="One or more application ids (will include run_after deps automatically).",
    )
    g.add_argument(
        "--include",
        help="Comma-separated list of application ids to include (no deps resolution).",
    )

    p.add_argument(
        "--threshold-gib",
        type=int,
        default=100,
        help="Free-space threshold (GiB) below which STORAGE_CONSTRAINED is enabled (default: 100).",
    )
    p.add_argument(
        "--force-storage-constrained",
        choices=["true", "false"],
        default=None,
        help="Override storage detection explicitly.",
    )
    p.add_argument(
        "--vars",
        default=None,
        help="JSON object merged into inventory variables (overrides win).",
    )
    p.add_argument(
        "--variant",
        type=int,
        default=_env_variant(),
        help=(
            "Pin the matrix init to a single round (zero-based index). "
            "Useful when only one variant of a multi-variant app needs to "
            "be (re-)materialised. Defaults to the VARIANT environment "
            "variable when set, otherwise full-matrix mode."
        ),
    )
    p.set_defaults(_handler=handler)


def _env_variant() -> int | None:
    raw = os.environ.get("VARIANT", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(
            f"VARIANT environment variable must be an integer, got {raw!r}"
        )


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()

    # `primary_apps` is the user-facing app list before transitive resolution.
    # The variant-aware planner expands each round's full include set
    # itself (services edges depend on variant-merged services maps), so
    # init no longer pre-resolves run_after / service deps here.
    if args.apps:
        primary_apps = [
            x.strip() for x in args.apps.replace(",", " ").split() if x.strip()
        ]
    else:
        primary_apps = [x.strip() for x in (args.include or "").split(",") if x.strip()]

    if not primary_apps:
        raise SystemExit("Primary app list is empty")

    # SERVICES_DISABLED removes provider roles from the inventory at
    # `infinito create inventory` time anyway, so do the same filter on
    # the primary list here. Otherwise the variant-aware resolver would
    # still pull a disabled provider in via service edges, only to have
    # the inventory step strip it back out — leaving the round's
    # include list inconsistent with what the inventory actually
    # contains.
    raw_disabled = os.environ.get("SERVICES_DISABLED", "").strip()
    disabled_app_ids: set[str] = set()
    if raw_disabled:
        services = parse_services_disabled(raw_disabled)
        roles_dir = compose.repo_root / "roles"
        provider_map = find_provider_roles(services, roles_dir)
        disabled_app_ids = set(provider_map.values())
        primary_apps = [a for a in primary_apps if a not in disabled_app_ids]

    if not primary_apps:
        raise SystemExit(
            "All primary apps disabled by SERVICES_DISABLED — nothing to initialise"
        )

    extra_vars: Dict[str, Any] | None = None
    if args.vars is not None:
        try:
            parsed = json.loads(args.vars)
        except Exception as exc:
            raise SystemExit(f"--vars must be valid JSON: {exc}")
        if not isinstance(parsed, dict):
            raise SystemExit("--vars must be a JSON object")
        extra_vars = parsed

    if args.force_storage_constrained is not None:
        storage_constrained = args.force_storage_constrained == "true"
    else:
        storage_constrained = detect_storage_constrained(
            compose, threshold_gib=int(args.threshold_gib)
        )

    plan = plan_dev_inventory_matrix(
        roles_dir=str(compose.repo_root / "roles"),
        primary_apps=primary_apps,
        base_inventory_dir=str(args.inventory_dir),
    )
    try:
        plan = filter_plan_to_variant(plan, args.variant)
    except ValueError as exc:
        raise SystemExit(f"--variant: {exc}")

    runtime = os.environ.get("RUNTIME") or detect_runtime()
    services_disabled = os.environ.get("SERVICES_DISABLED", "")
    for _round_index, inv_dir, round_variants, include_R in plan:
        round_include = tuple(
            role for role in include_R if role not in disabled_app_ids
        )
        if not round_include:
            print(
                f">>> Skipping inventory at {inv_dir}: include set is empty "
                "after SERVICES_DISABLED filter"
            )
            continue
        spec = DevInventorySpec(
            inventory_dir=inv_dir,
            include=round_include,
            storage_constrained=storage_constrained,
            runtime=runtime,
            extra_vars=extra_vars,
            services_disabled=services_disabled,
            active_variants=round_variants,
        )
        build_dev_inventory(compose, spec)

    if len(plan) == 1:
        _, inv_dir, round_variants, include_R = plan[0]
        non_zero = {a: i for a, i in round_variants.items() if i}
        suffix = f" variants={non_zero}" if non_zero else ""
        print(
            f">>> Inventory initialized at {inv_dir} "
            f"(include={','.join(include_R)} "
            f"storage_constrained={storage_constrained}){suffix}"
        )
    else:
        print(
            f">>> Matrix inventory initialized in {len(plan)} folders "
            f"(primary_apps={','.join(primary_apps)} "
            f"storage_constrained={storage_constrained}):"
        )
        for round_index, inv_dir, round_variants, include_R in plan:
            non_zero = {a: i for a, i in round_variants.items() if i}
            print(
                f"    [round {round_index}] {inv_dir} "
                f"include={','.join(include_R)}"
                + (f"  variants={non_zero}" if non_zero else "")
            )
    return 0
