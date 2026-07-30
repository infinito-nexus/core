from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from cli.administration.inventory.provision.services_disabler import (
    find_provider_roles,
    parse_services_disabled,
)
from cli.meta.runtime import detect_runtime

from .common import make_compose
from .inventory import (
    DevInventorySpec,
    build_dev_inventory,
    plan_dev_inventory_matrix,
    prune_orphans_after_disable,
)
from .inventory import (
    _build_services_overrides_for_round as build_services_overrides_for_round,
)
from .storage import detect_storage_constrained
from .variant_select import add_variant_args, apply_variant_filter

if TYPE_CHECKING:
    import argparse


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "init",
        help="Create development inventory inside the infinito container.",
    )
    p.add_argument(
        "--inventory-dir",
        default=os.environ.get("INFINITO_INVENTORY_DIR"),
        required=os.environ.get("INFINITO_INVENTORY_DIR") is None,
        help=(
            "Inventory directory base (default: $INFINITO_INVENTORY_DIR). "
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
    add_variant_args(p, action="init")
    p.set_defaults(_handler=handler)


def handler(args: argparse.Namespace) -> int:
    compose = make_compose()

    if args.apps:
        primary_apps = [
            x.strip() for x in args.apps.replace(",", " ").split() if x.strip()
        ]
    else:
        primary_apps = [x.strip() for x in (args.include or "").split(",") if x.strip()]

    if not primary_apps:
        raise SystemExit("Primary app list is empty")

    raw_disabled = os.environ.get("disable", "").strip()
    disabled_app_ids: set[str] = set()
    if raw_disabled:
        services = parse_services_disabled(raw_disabled)
        roles_dir = compose.repo_root / "roles"
        provider_map = find_provider_roles(services, roles_dir)
        disabled_app_ids = set(provider_map.values())
        primary_apps = [a for a in primary_apps if a not in disabled_app_ids]

    if not primary_apps:
        raise SystemExit(
            "All primary apps disabled by `disable` — nothing to initialise"
        )

    extra_vars: dict[str, Any] | None = None
    if args.vars is not None:
        try:
            parsed = json.loads(args.vars)
        except Exception as exc:
            raise SystemExit(f"--vars must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("--vars must be a JSON object")
        extra_vars = parsed

    forced_storage_constrained = (
        None
        if args.force_storage_constrained is None
        else args.force_storage_constrained == "true"
    )

    plan = plan_dev_inventory_matrix(
        roles_dir=str(compose.repo_root / "roles"),
        primary_apps=primary_apps,
        base_inventory_dir=str(args.inventory_dir),
    )
    try:
        plan = apply_variant_filter(plan, args)
    except ValueError as exc:
        raise SystemExit(f"--variant: {exc}") from exc

    runtime = os.environ.get("RUNTIME") or detect_runtime()
    services_disabled = os.environ.get("disable", "")
    roles_dir = str(compose.repo_root / "roles")
    built_includes: dict[str, tuple[str, ...]] = {}
    round_storage_constrained: dict[str, bool] = {}
    for _round_index, inv_dir, round_variants, include_R, _purge_set in plan:
        if disabled_app_ids:
            round_overrides = build_services_overrides_for_round(
                roles_dir=roles_dir,
                round_index=_round_index,
                primary_app_variants={
                    a: round_variants[a] for a in primary_apps if a in round_variants
                },
            )
            round_include, pruned = prune_orphans_after_disable(
                include=include_R,
                primary_apps=primary_apps,
                disabled_app_ids=disabled_app_ids,
                services_overrides=round_overrides,
            )
            if pruned:
                print(
                    f">>> `disable` orphan-pruned {len(pruned)} transitive dep(s) "
                    f"at {inv_dir}: {','.join(pruned)}"
                )
        else:
            round_include = include_R
        if not round_include:
            print(
                f">>> Skipping inventory at {inv_dir}: include set is empty "
                "after `disable` filter"
            )
            continue
        built_includes[inv_dir] = round_include
        storage_constrained = (
            forced_storage_constrained
            if forced_storage_constrained is not None
            else detect_storage_constrained(compose, primary_apps, round_variants)
        )
        round_storage_constrained[inv_dir] = storage_constrained
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
        _, inv_dir, round_variants, include_R, _purge_set = plan[0]
        non_zero = {a: i for a, i in round_variants.items() if i}
        suffix = f" variants={non_zero}" if non_zero else ""
        shown = built_includes.get(inv_dir, include_R)
        print(
            f">>> Inventory initialized at {inv_dir} "
            f"(include={','.join(shown)} "
            f"storage_constrained={round_storage_constrained.get(inv_dir)}){suffix}"
        )
    else:
        print(
            f">>> Matrix inventory initialized in {len(plan)} folders "
            f"(primary_apps={','.join(primary_apps)}):"
        )
        for round_index, inv_dir, round_variants, include_R, _purge_set in plan:
            non_zero = {a: i for a, i in round_variants.items() if i}
            shown = built_includes.get(inv_dir, include_R)
            print(
                f"    [round {round_index}] {inv_dir} "
                f"include={','.join(shown)} "
                f"storage_constrained={round_storage_constrained.get(inv_dir)}"
                + (f"  variants={non_zero}" if non_zero else "")
            )
    return 0
