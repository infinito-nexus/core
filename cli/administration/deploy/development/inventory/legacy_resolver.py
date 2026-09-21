"""Default (non-variant) include resolution for the matrix planner.

When NO primary app ships a `meta/variants.yml`, the planner falls back
to this path — the `CombinedResolver` walks `dependencies` and
`shared:`-edges in the variant-merged services map and Jinja flags are
evaluated at deploy time against `group_names`. `run_after` is NOT
followed for inclusion (it is a pure ordering hint), so a variant that
disables a service does not get the provider re-added through the
ordering edge. This module owns the include resolution that path needs
and nothing else; the round's variant-merged services maps come from
`utils.roles.applications.variants`, which the CI selection resolves its
closure from as well.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.applications.variants import services_overrides_for_round

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_build_services_overrides_for_round = services_overrides_for_round


def _resolve_round_include(
    *,
    primary_apps: Sequence[str],
    services_overrides: dict[str, dict],
) -> tuple[str, ...]:
    """Resolve transitive prerequisites for each primary app under a
    round's variant-merged services map. Returns the full include set
    in stable order (deps first per primary, primary last; primaries
    iterated in the user-provided order).

    The resolver import is deferred so the host-side import surface
    stays lean for callers that never need the variant-aware planner
    (e.g. lint/validation).
    """
    from cli.meta.roles.applications.resolution.combined.resolver import (
        CombinedResolver,
    )

    resolver = CombinedResolver(
        services_overrides=services_overrides, follow_run_after=False
    )
    out: list[str] = []
    seen: set[str] = set()
    for app_id in primary_apps:
        deps = resolver.resolve(app_id)
        for dep in deps:
            if dep != app_id and dep not in seen:
                out.append(dep)
                seen.add(dep)
        if app_id not in seen:
            out.append(app_id)
            seen.add(app_id)
    return tuple(out)


def prune_orphans_after_disable(
    *,
    include: Sequence[str],
    primary_apps: Sequence[str],
    disabled_app_ids: Iterable[str],
    services_overrides: dict[str, dict],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a round's ``include`` into ``(kept, pruned)`` after `disable`.

    `kept` are the members still reachable from a surviving primary app
    once every role in `disabled_app_ids` is cut from the graph; `pruned`
    are the orphaned remainder (the disabled roots themselves excluded).
    Reachability walks the same `dependencies` + `services` edges the
    round's closure was built from — `run_after` is NOT followed, matching
    ``CombinedResolver(follow_run_after=False)`` — using `services_overrides`
    so the variant-merged topology matches what the inventory bakes.

    Returned order follows `include` for both tuples.

    Args:
        include: the round's full closure (deps-first, primary last).
        primary_apps: the operator-selected roots (already `disable`-filtered).
        disabled_app_ids: provider roles cut by `disable`.
        services_overrides: round variant-merged services maps per role.
    """
    from cli.meta.roles.applications.resolution.combined.resolver import (
        CombinedResolver,
    )

    disabled = set(disabled_app_ids)
    resolver = CombinedResolver(
        services_overrides=services_overrides, follow_run_after=False
    )
    reachable: set[str] = set()
    stack = [a for a in primary_apps if a not in disabled]
    while stack:
        node = stack.pop()
        if node in reachable or node in disabled:
            continue
        reachable.add(node)
        edges = resolver.edges_for(node)
        stack.extend(
            dep
            for dep in (*edges.dependencies, *edges.services)
            if dep not in reachable and dep not in disabled
        )
    kept = tuple(role for role in include if role in reachable)
    pruned = tuple(
        role for role in include if role not in reachable and role not in disabled
    )
    return kept, pruned
