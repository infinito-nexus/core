"""Orphan pruning for the matrix planner's rounds after a `disable`.

When NO primary app ships a `meta/variants.yml`, the planner falls back
to the `CombinedResolver`, which walks `dependencies` and `shared:`-edges
in the variant-merged services map; Jinja flags are evaluated at deploy
time against `group_names`. `run_after` is NOT followed for inclusion (it
is a pure ordering hint), so a variant that disables a service does not
get the provider re-added through the ordering edge. The round's include
set and its variant-merged services maps come from
`utils.roles.applications.variants`, which the CI selection resolves its
closure from as well; this module cuts that include once `disable` drops
a provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


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
