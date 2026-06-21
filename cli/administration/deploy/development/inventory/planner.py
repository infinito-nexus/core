"""Matrix-deploy planner.

Pure function — reads role metadata via cached YAML helpers and emits
``PlanEntry`` tuples; no filesystem side effects. The include set per
round is resolved by the ``CombinedResolver`` (see ``.legacy_resolver``):
each role contributes its own pulled-in providers and the include is
the union. A service-key is therefore pulled in as soon as ANY role in
the round-aware closure says it should be (literal ``True`` OR the
``"{{ '<role>' in group_names }}"`` Jinja form, both accepted by
``utils.roles.applications.services.registry.is_explicit_truth``); if
EVERY role marks it ``False`` it stays out of the include.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.applications import get_variants

from . import legacy_resolver

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .spec import PlanEntry


def filter_plan_to_variants(
    plan: list[PlanEntry],
    variants: list[int] | None,
) -> list[PlanEntry]:
    """Pin a matrix plan to a subset of rounds when `variants` is set.

    `variants=None` returns the plan unchanged (full-matrix mode). This is the
    runner-split entry point: a role with more variants than one runner should
    iterate is sliced into bundles (e.g. ``0,1,2`` on one runner and ``3,4`` on
    the next), each bundle passed as `variants`. Out-of-range indices raise
    `ValueError` so the caller surfaces a clean operator error.
    """
    if variants is None:
        return plan
    available = sorted(entry[0] for entry in plan)
    missing = sorted(v for v in variants if v not in available)
    if missing:
        raise ValueError(
            f"variants {missing} out of range; available rounds: {available}"
        )
    wanted = set(variants)
    return [entry for entry in plan if entry[0] in wanted]


def plan_dev_inventory_matrix(
    *,
    roles_dir: str,
    primary_apps: Sequence[str],
    base_inventory_dir: str,
) -> list[PlanEntry]:
    """Return ``[(round_index, inventory_dir, round_variants, include, purge_set), ...]`` — per-round variant-closure plus a plan-constant union for the inter-round wipe."""
    if not primary_apps:
        raise ValueError("plan_dev_inventory_matrix: primary_apps must not be empty")

    variants_per_app = get_variants(roles_dir=roles_dir)
    primary_variant_counts = {
        app_id: max(1, len(variants_per_app.get(app_id) or [{}]))
        for app_id in primary_apps
    }
    total_rounds = max(primary_variant_counts.values(), default=1)
    base = str(base_inventory_dir).rstrip("/")

    # WHY split: per-round include is variant-specific; purge_set is the union so the inter-round wipe clears every variant's footprint, not just the previous round's slice.
    per_variant_includes: list[tuple[str, ...]] = []
    primary_round_variants_per_round: list[dict[str, int]] = []
    for round_index in range(total_rounds):
        primary_round_variants = {
            app_id: round_index if round_index < count else 0
            for app_id, count in primary_variant_counts.items()
        }
        primary_round_variants_per_round.append(primary_round_variants)

        services_overrides = legacy_resolver._build_services_overrides_for_round(
            roles_dir=roles_dir,
            round_index=round_index,
            primary_app_variants=primary_round_variants,
        )
        per_variant_includes.append(
            legacy_resolver._resolve_round_include(
                primary_apps=primary_apps,
                services_overrides=services_overrides,
            )
        )

    seen_union: set[str] = set()
    union_apps: list[str] = []
    for variant_include in per_variant_includes:
        for dep in variant_include:
            if dep not in seen_union:
                seen_union.add(dep)
                union_apps.append(dep)
    purge_set: tuple[str, ...] = tuple(union_apps)

    plan: list[PlanEntry] = []
    for round_index in range(total_rounds):
        primary_round_variants = primary_round_variants_per_round[round_index]
        round_include = per_variant_includes[round_index]

        round_variants = dict(primary_round_variants)
        for dep in round_include:
            if dep in round_variants:
                continue
            dep_variants = variants_per_app.get(dep) or [{}]
            dep_count = max(1, len(dep_variants))
            round_variants[dep] = round_index if round_index < dep_count else 0

        inv_dir = f"{base}-{round_index}" if total_rounds > 1 else base
        plan.append((round_index, inv_dir, round_variants, round_include, purge_set))

    return plan
