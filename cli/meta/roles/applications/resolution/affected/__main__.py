#!/usr/bin/env python3
"""
Resolve the set of roles affected by a change to a given set of seed roles.

A role R is "affected" by seed S iff S appears in R's transitive prerequisite
closure (run_after + dependencies + services), as defined by
:class:`cli.meta.roles.applications.resolution.combined.resolver.CombinedResolver`.

Usage:
  python -m cli.meta.roles.applications.resolution.affected --changed-roles ROLE [ROLE ...]

Output:
  Whitespace-separated, sorted list of affected role names (single line),
  including the seed roles themselves.

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

if TYPE_CHECKING:
    from collections.abc import Iterable

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Print all roles whose transitive prerequisite closure "
            "(run_after + dependencies + services) contains any of the "
            "given seed roles. Seed roles themselves are included."
        )
    )
    parser.add_argument(
        "--changed-roles",
        nargs="+",
        required=True,
        help="Seed role names (folder names under ./roles).",
    )
    args = parser.parse_args()
    print(" ".join(affected_roles(args.changed_roles)))


if __name__ == "__main__":
    main()
