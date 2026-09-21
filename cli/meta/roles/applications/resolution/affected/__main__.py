#!/usr/bin/env python3
"""
Resolve the set of roles affected by a change to a given set of seed roles.

A role R is "affected" by seed S iff S appears in R's transitive prerequisite
closure (run_after + dependencies + services), as defined by
:class:`cli.meta.roles.applications.resolution.combined.resolver.CombinedResolver`.

Usage:
  python -m cli.meta.roles.applications.resolution.affected --changed-roles ROLE [ROLE ...]

Output:
  Whitespace-separated, sorted list of selection tokens (single line),
  including the seed roles themselves. A role whose variants do not all
  reach a seed is narrowed to the ones that do (``role#0,2``,
  :mod:`utils.github.variant.selection`): a variant that switches its
  provider off does not inherit the seed's change, so deploying it verifies
  nothing. The narrowing is transitive over the whole chain, because each
  round's closure is walked on that round's variant-merged services maps.

Exit codes:
  0  Success. The closure was computed and printed.
  1  Resolver error or unknown seed.
  2  At least one seed role is non-modellable in the resolver
     (no application_id and not referenced by any role's run_after).
     Callers MUST treat this as "fall back to a full deploy" because
     the resolver cannot guarantee that downstream consumers are
     enumerated for that seed.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from cli.meta.roles.applications.resolution.combined.errors import (
    CombinedResolutionError,
)
from cli.meta.roles.applications.resolution.combined.repo_paths import roles_dir
from cli.meta.roles.applications.resolution.combined.resolver import CombinedResolver
from cli.meta.roles.applications.resolution.combined.role_introspection import (
    has_application_id,
    load_run_after,
)
from utils.cache.applications import get_variants
from utils.roles.applications.variants import services_overrides_for_round
from utils.roles.display import VARIANT_SEPARATOR

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

EXIT_NON_MODELLABLE_SEED = 2


def _list_role_names() -> list[str]:
    rdir = roles_dir()
    if not rdir.is_dir():
        return []
    return sorted(p.name for p in rdir.iterdir() if p.is_dir())


def _non_modellable_seeds(seeds: set[str], all_roles: list[str]) -> list[str]:
    """Return seeds that the resolver cannot reach as a downstream prereq.

    A seed is reachable iff at least one of:
      * it has ``application_id`` (then app-deps and shared-service edges
        from any consumer can include it), or
      * some role lists it in its ``run_after`` (then a run_after edge
        from that consumer includes it).

    Any other seed (e.g. a non-app helper role only pulled in via
    ``include_role`` from tasks) is invisible to the resolver. Returning
    a partial closure for such a seed silently shrinks the deploy
    matrix. Callers MUST fall back to a full deploy in that case.
    """

    if not seeds:
        return []

    run_after_index: set[str] = set()
    for role in all_roles:
        try:
            for target in load_run_after(role):
                run_after_index.add(target)
        except CombinedResolutionError:
            continue

    out: list[str] = []
    for seed in sorted(seeds):
        if has_application_id(seed):
            continue
        if seed in run_after_index:
            continue
        out.append(seed)
    return out


def affected_roles(changed: Iterable[str]) -> list[str]:
    seeds: set[str] = {r.strip() for r in changed if r and r.strip()}
    if not seeds:
        return []

    all_roles = _list_role_names()
    unknown = seeds - set(all_roles)
    if unknown:
        raise SystemExit(
            f"Unknown role(s) passed via --changed-roles: {sorted(unknown)}"
        )

    non_modellable = _non_modellable_seeds(seeds, all_roles)
    if non_modellable:
        print(
            "non-modellable seed(s) for resolver: "
            f"{non_modellable}; caller must fall back to full deploy",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_NON_MODELLABLE_SEED)

    resolver = CombinedResolver()
    affected: set[str] = set(seeds)

    for role in all_roles:
        if role in affected:
            continue
        prereqs = resolver.resolve(role)
        if any(p in seeds for p in prereqs):
            affected.add(role)

    return sorted(affected)


def _round_resolvers(roles_path: Path, rounds: int) -> list[CombinedResolver]:
    """One resolver per deploy round, each walking that round's
    variant-merged services maps.

    The maps are built by the same helper
    (:func:`utils.roles.applications.variants.services_overrides_for_round`)
    the matrix planner feeds its rounds from, so the topology this reads is
    the topology round ``i`` deploys -- including every pulled-in role's own
    variant, which is what carries the narrowing across generations.
    ``run_after`` is not followed, for the reason the planner does not follow
    it either: an ordering hint would re-add a provider the variant switched
    off.
    """
    return [
        CombinedResolver(
            services_overrides=services_overrides_for_round(
                roles_dir=str(roles_path),
                round_index=index,
                primary_app_variants={},
            ),
            follow_run_after=False,
        )
        for index in range(rounds)
    ]


def _pinned(
    role: str, seeds: set[str], resolvers: Sequence[CombinedResolver], count: int
) -> str:
    """*role*, narrowed to the variants whose own closure reaches a seed.

    Returns the bare role id whenever the narrowing cannot be trusted: no
    variant reaching a seed means the role is affected through an edge the
    round closure does not model (a ``run_after`` hint, or a resolution the
    variant merge refused), and verifying none of it is worse than verifying
    all of it.
    """
    try:
        hits = [
            index
            for index in range(count)
            if seeds.intersection(resolvers[index].resolve(role))
        ]
    except CombinedResolutionError:
        return role
    if not hits or len(hits) == count:
        return role
    return role + VARIANT_SEPARATOR + ",".join(str(index) for index in hits)


def affected_selection(changed: Iterable[str]) -> list[str]:
    """:func:`affected_roles` as selection tokens, variant-narrowed.

    A seed role keeps every variant: its own files changed, so each of them
    has to redeploy regardless of which providers it pulls.
    """
    seeds: set[str] = {r.strip() for r in changed if r and r.strip()}
    affected = affected_roles(changed)
    variants = get_variants(roles_dir=str(roles_dir()))
    counts = {role: len(variants.get(role) or ()) for role in affected}
    rounds = max(counts.values(), default=0)
    if rounds < 2:
        return affected
    resolvers = _round_resolvers(roles_dir(), rounds)
    return [
        role
        if role in seeds or counts[role] < 2
        else _pinned(role, seeds, resolvers, counts[role])
        for role in affected
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Print all roles whose transitive prerequisite closure "
            "(run_after + dependencies + services) contains any of the "
            "given seed roles, each narrowed to the variants that reach one. "
            "Seed roles themselves are included, with every variant."
        )
    )
    parser.add_argument(
        "--changed-roles",
        nargs="+",
        required=True,
        help="Seed role names (folder names under ./roles).",
    )
    args = parser.parse_args()
    print(" ".join(affected_selection(args.changed_roles)))


if __name__ == "__main__":
    main()
