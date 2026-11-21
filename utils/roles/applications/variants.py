"""What one round's variants mean for the roles that round pulls in.

A round picks one variant per role, and that choice decides two things no
single role's `meta/services.yml` can state on its own: which providers the
role still pulls in, and how lean those providers have to be
(:mod:`utils.roles.applications.topics`). Both are resolved here, so the
matrix planner's include set, the inventory bake and the CI selection read
one answer instead of three.

The module is deliberately free of deploy-runtime imports: the CI selection
resolves its closure on a runner that has no inventory, no container and no
`INFINITO_SRC_DIR`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.applications import get_variants
from utils.roles.applications.variant.pins import VariantPinError, resolve_pins
from utils.roles.applications.variant.services import (
    PRIMARY_ONLY_SERVICE_KEYS,
    SEMAPHORE_SERVICE_KEY,
    collect_provider_overrides,
    overrides_for_assignment,
    primary_only,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "PRIMARY_ONLY_SERVICE_KEYS",
    "SEMAPHORE_SERVICE_KEY",
    "ResolvedRound",
    "active_variants_for_round",
    "clamped_assignment",
    "collect_provider_overrides",
    "primary_only",
    "resolve_round",
    "round_under",
    "services_overrides_for_round",
]


@dataclass(frozen=True)
class ResolvedRound:
    """One round once its variant pins have settled.

    Attributes:
        active_index: role -> the variant index the round runs it in.
        services_overrides: role -> its services map under that variant.
        include: the round's include set, deps first and primaries last.
    """

    active_index: dict[str, int]
    services_overrides: dict[str, dict]
    include: tuple[str, ...]


def clamped_assignment(
    *,
    round_index: int,
    primary_app_variants: Mapping[str, int],
    variants_per_app: Mapping[str, list],
) -> dict[str, int]:
    """Return the variant every role starts a round on, before any pin.

    Args:
        round_index: the round of the sweep; a role with fewer variants falls
            back to variant 0.
        primary_app_variants: the already clamped index of every primary app.
        variants_per_app: parsed variants per role.
    """

    def _round_index_for(role_name: str, variant_list: list) -> int:
        variant_count = max(1, len(variant_list))
        if role_name in primary_app_variants:
            idx = primary_app_variants[role_name]
        else:
            idx = round_index if round_index < variant_count else 0
        return idx if 0 <= idx < len(variant_list) else 0

    return {
        role_name: _round_index_for(role_name, variant_list)
        for role_name, variant_list in variants_per_app.items()
        if variant_list
    }


def _resolve_round_include(
    *,
    primary_apps: Sequence[str],
    services_overrides: dict[str, dict],
) -> tuple[str, ...]:
    """Resolve transitive prerequisites for each primary app under a
    round's variant-merged services map. Returns the full include set
    in stable order (deps first per primary, primary last; primaries
    iterated in the user-provided order).

    A non-invokable prerequisite is dropped from the result. The include
    set becomes an inventory group per entry and a deploy id the play
    dispatches, and `utils.roles.stage` only ever loops over invokable
    paths, so a non-invokable id could never be dispatched from one.
    Keeping it would abort the round before ansible starts, which is
    what `user-workstation` did to every desktop round, and inventing a
    group for it instead would produce one nothing dispatches. The role
    still reaches the host through whatever pulled it into the closure:
    a meta dependency, or the service edge `sys-service-loader` reads.

    The resolver import is deferred so the host-side import surface
    stays lean for callers that never need the variant-aware planner
    (e.g. lint/validation).
    """
    from cli.meta.roles.applications.resolution.combined.resolver import (
        CombinedResolver,
    )
    from utils.roles.required_by_coverage import role_is_invokable

    resolver = CombinedResolver(
        services_overrides=services_overrides, follow_run_after=False
    )
    out: list[str] = []
    seen: set[str] = set()
    for app_id in primary_apps:
        deps = resolver.resolve(app_id)
        for dep in deps:
            if dep != app_id and dep not in seen and role_is_invokable(dep):
                out.append(dep)
                seen.add(dep)
        if app_id not in seen:
            out.append(app_id)
            seen.add(app_id)
    return tuple(out)


def round_under(
    active_index: Mapping[str, int],
    *,
    roles_dir: str,
    primary_app_variants: Mapping[str, int],
    variants_per_app: Mapping[str, list],
) -> tuple[ResolvedRound, dict[str, int]]:
    """Return what one assignment deploys and the pins in force under it.

    A ``# variant-pin:`` in ``R#i`` is in force only while ``R`` is in the
    include running variant ``i``, and no pin moves a primary app.

    Args:
        active_index: role -> the variant index to evaluate the round at.
        roles_dir: roles directory the services maps and pins are read from.
        primary_app_variants: the round's primary apps, in the order the
            include resolves them.
        variants_per_app: parsed variants per role.

    Returns:
        The round under ``active_index``, and ``{role: index}`` for every
        non-primary role a pin in force moves.
    """
    overrides = overrides_for_assignment(
        active_index,
        roles_dir=roles_dir,
        primary_app_variants=primary_app_variants,
        variants_per_app=variants_per_app,
    )
    include = tuple(
        _resolve_round_include(
            primary_apps=list(primary_app_variants),
            services_overrides=overrides,
        )
    )
    pinned = resolve_pins(
        {role: active_index[role] for role in include if role in active_index},
        roles_dir=roles_dir,
        variants_per_app=variants_per_app,
    )
    forced = {
        role: index
        for role, index in pinned.items()
        if role not in primary_app_variants and role in active_index
    }
    return (
        ResolvedRound(
            active_index=dict(active_index),
            services_overrides=overrides,
            include=include,
        ),
        forced,
    )


def resolve_round(
    *,
    roles_dir: str,
    round_index: int,
    primary_app_variants: Mapping[str, int],
    variants_per_app: Mapping[str, list],
) -> ResolvedRound:
    """Settle the variant every role runs in one round, and what that deploys.

    Starting from :func:`clamped_assignment`, each step evaluates
    :func:`round_under` and moves to the clamped indices plus the pins in
    force; the round is the first assignment a step reproduces.

    Args:
        roles_dir: roles directory the services maps and pins are read from.
        round_index: the round of the sweep.
        primary_app_variants: the already clamped index of every primary app,
            in the order the include resolves them.
        variants_per_app: parsed variants per role.

    Raises:
        VariantPinError: the pins never settle on one assignment.
    """
    clamped = clamped_assignment(
        round_index=round_index,
        primary_app_variants=primary_app_variants,
        variants_per_app=variants_per_app,
    )
    active_index = dict(clamped)
    visited: list[dict[str, int]] = []
    while active_index not in visited:
        visited.append(active_index)
        resolved, forced = round_under(
            active_index,
            roles_dir=roles_dir,
            primary_app_variants=primary_app_variants,
            variants_per_app=variants_per_app,
        )
        settled = {**clamped, **forced}
        if settled == active_index:
            return resolved
        active_index = settled
    raise VariantPinError(
        f"round {round_index} with primaries {dict(primary_app_variants)}: "
        f"the variant pins cycle through {len(visited)} assignments without "
        f"settling on one"
    )


def active_variants_for_round(
    *,
    roles_dir: str,
    round_index: int,
    primary_app_variants: Mapping[str, int],
    variants_per_app: Mapping[str, list],
) -> dict[str, int]:
    """Return ``{role: variant index}`` one round runs every role with variants in.

    Args:
        roles_dir: roles directory the ``# variant-pin:`` markers are read from.
        round_index: the round of the sweep.
        primary_app_variants: the already clamped index of every primary app;
            no pin overrides it.
        variants_per_app: parsed variants per role.

    Returns:
        The assignment :func:`resolve_round` settles on.

    Raises:
        VariantPinError: the pins never settle on one assignment.
    """
    return resolve_round(
        roles_dir=roles_dir,
        round_index=round_index,
        primary_app_variants=primary_app_variants,
        variants_per_app=variants_per_app,
    ).active_index


def services_overrides_for_round(
    *,
    roles_dir: str,
    round_index: int,
    primary_app_variants: Mapping[str, int],
) -> dict[str, dict]:
    """For every role with `meta/variants.yml`, return the services map
    that results from merging the round's variant payload onto the
    role's on-disk `meta/services.yml`.

    Each role runs the variant :func:`resolve_round` settles on: the clamped
    round index, the supplied index for a primary app, or the index a
    `# variant-pin:` in force forces (see
    :mod:`utils.roles.applications.variant.pins`). Every host of
    :data:`PRIMARY_ONLY_SERVICE_KEYS` stays on only where a primary app's
    variant declares it; every other role has it off.
    Roles without variants are absent from the result so the resolver
    falls through to its disk-read path.

    The merged map is what the inventory ALSO bakes into host_vars, so
    feeding the same dict into `CombinedResolver(services_overrides=...)`
    eliminates the topology-vs-host_vars drift that variant-blind
    resolution produced.
    """
    return resolve_round(
        roles_dir=roles_dir,
        round_index=round_index,
        primary_app_variants=primary_app_variants,
        variants_per_app=get_variants(roles_dir=roles_dir, readonly=True),
    ).services_overrides
