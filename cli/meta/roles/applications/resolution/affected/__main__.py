#!/usr/bin/env python3
"""
Resolve the set of roles affected by a change to a given set of seed roles.

Usage:
  python -m cli.meta.roles.applications.resolution.affected --changed-roles ROLE [ROLE ...]

Output:
  Whitespace-separated, sorted list of selection tokens (single line),
  including the seed roles themselves and every role that runs one of them
  through an ungated ``include_role``/``import_role``, transitively, each
  with all its variants. Every other role is kept only with
  the variants whose round really deploys a seed (``role#0,2``,
  :mod:`utils.github.variant.selection`), and dropped when none does: a
  variant that switches its provider off, or reaches the seed only over a
  ``run_after`` ordering hint, does not inherit the seed's change, so
  deploying it verifies nothing. The narrowing is transitive over the whole
  chain, because each round's closure is walked on that round's
  variant-merged services maps.

Exit codes:
  0  Success. The closure was computed and printed.
  1  Resolver error or unknown seed.
  2  At least one seed role is non-modellable in the resolver
     (no application_id, so no round closure can contain it).
     Callers MUST treat this as "fall back to a full deploy" because
     the resolver cannot guarantee that downstream consumers are
     enumerated for that seed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

from cli.meta.roles.applications.resolution.combined.errors import (
    CombinedResolutionError,
)
from cli.meta.roles.applications.resolution.combined.repo_paths import (
    role_config_path,
    roles_dir,
)
from cli.meta.roles.applications.resolution.combined.resolver import CombinedResolver
from cli.meta.roles.applications.resolution.combined.role_introspection import (
    has_application_id,
)
from cli.meta.roles.applications.resolution.combined.yaml_utils import load_yaml_file
from utils.cache.applications import get_variants
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    is_explicit_truth,
)
from utils.roles.applications.topics import provider_of
from utils.roles.applications.variants import resolve_round
from utils.roles.display import VARIANT_SEPARATOR
from utils.roles.invocations import role_includes

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

EXIT_NON_MODELLABLE_SEED = 2


def _list_role_names() -> list[str]:
    rdir = roles_dir()
    if not rdir.is_dir():
        return []
    return sorted(p.name for p in rdir.iterdir() if p.is_dir())


def _non_modellable_seeds(seeds: set[str]) -> list[str]:
    """
    Args:
        seeds: the changed roles.

    Returns:
        Every seed without ``application_id``, sorted. A round pulls a role
        in only over app-only ``dependencies`` and ``services`` edges, never
        over ``run_after``, so the resolver cannot enumerate who deploys
        such a seed and the caller MUST fall back to a full deploy.
    """
    return sorted(role for role in seeds if not has_application_id(role))


def _switched_on(blocks: list[Mapping]) -> dict[str, dict]:
    """
    Args:
        blocks: services maps of one role.

    Returns:
        ``{key: enabled and shared}`` for each key some block marks
        ``enabled`` and some block marks ``shared`` with an explicit truth,
        which every deep merge of those blocks needs before it pulls the
        key's provider in.
    """

    def flagged(flag: str) -> set[str]:
        return {
            str(key)
            for block in blocks
            for key, entry in block.items()
            if isinstance(entry, Mapping) and is_explicit_truth(entry.get(flag))
        }

    return {
        key: {"enabled": True, "shared": True}
        for key in flagged("enabled") & flagged("shared")
    }


def _own_blocks(name: str, variants: Mapping[str, list]) -> list[Mapping]:
    """
    Args:
        name: a role.
        variants: parsed variants per role.

    Returns:
        The role's ``meta/services.yml`` and each of its variants'
        ``services`` blocks, the mappings among them.
    """
    path = role_config_path(name)
    blocks = [
        load_yaml_file(path) if path.exists() else {},
        *(
            payload.get("services")
            for payload in variants.get(name) or ()
            if isinstance(payload, Mapping)
        ),
    ]
    return [block for block in blocks if isinstance(block, Mapping)]


def _nested_demands(
    sources: Mapping[str, list[Mapping]], registry: Mapping
) -> list[tuple[str, Mapping]]:
    """
    Args:
        sources: services blocks per role.
        registry: the service registry of the roles tree.

    Returns:
        ``(provider, demand)`` for every nested ``services`` map a block
        places on one of its keys, with the provider of that key.
    """
    return [
        (provider_of(str(key), registry), entry["services"])
        for blocks in sources.values()
        for block in blocks
        for key, entry in block.items()
        if isinstance(entry, Mapping) and isinstance(entry.get("services"), Mapping)
    ]


def _union_services(
    names: list[str], variants: Mapping[str, list]
) -> dict[str, dict[str, dict]]:
    """
    Args:
        names: every role.
        variants: parsed variants per role.

    Returns:
        ``{role: services map}`` built by :func:`_switched_on` from the
        role's ``meta/services.yml``, each variant's ``services`` block, and
        every nested ``services`` demand another role's block makes of it,
        the three sources a round deep-merges its map from.
    """
    sources = {name: _own_blocks(name, variants) for name in names}
    registry = build_service_registry_from_roles_dir(roles_dir())
    for provider, demand in _nested_demands(sources, registry):
        if provider in sources:
            sources[provider].append(demand)
    return {name: _switched_on(blocks) for name, blocks in sources.items()}


def _with_includers(seeds: set[str], names: list[str]) -> set[str]:
    """
    Args:
        seeds: the changed roles.
        names: every role.

    Returns:
        *seeds* plus every role that includes one of them, transitively, per
        :func:`utils.roles.invocations.role_includes`.
    """
    path = str(roles_dir())
    found = set(seeds)
    frontier = set(seeds)
    while frontier:
        frontier = {
            name for name in names if frontier & role_includes(path, name)
        } - found
        found |= frontier
    return found


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

    non_modellable = _non_modellable_seeds(seeds)
    if non_modellable:
        print(
            "non-modellable seed(s) for resolver: "
            f"{non_modellable}; caller must fall back to full deploy",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_NON_MODELLABLE_SEED)

    resolver = CombinedResolver(
        services_overrides=_union_services(
            all_roles, get_variants(roles_dir=str(roles_dir()), readonly=True)
        ),
        follow_run_after=False,
    )
    changed_roles = _with_includers(seeds, all_roles)
    return sorted(
        changed_roles
        | {
            role
            for role in all_roles
            if role not in changed_roles
            and changed_roles.intersection(resolver.resolve(role))
        }
    )


def _round_resolver(
    roles_path: Path, role: str, index: int, variants: Mapping[str, list]
) -> CombinedResolver:
    """The resolver of the round that deploys *role* in variant *index*.

    The round is the one the matrix planner deploys for that variant
    (:func:`utils.roles.applications.variants.resolve_round` with *role* as
    its only primary), so the topology this reads carries every variant pin
    in force there and every pulled-in role's own variant, which is what
    carries the narrowing across generations. ``run_after`` is not followed,
    for the reason the planner does not follow it either: an ordering hint
    would re-add a provider the variant switched off.

    Args:
        roles_path: the roles tree.
        role: the round's primary app.
        index: the variant *role* runs in.
        variants: parsed variants per role.
    """
    return CombinedResolver(
        services_overrides=resolve_round(
            roles_dir=str(roles_path),
            round_index=index,
            primary_app_variants={role: index},
            variants_per_app=variants,
        ).services_overrides,
        follow_run_after=False,
    )


def _pinned(
    role: str,
    seeds: set[str],
    count: int,
    roles_path: Path,
    variants: Mapping[str, list],
) -> str | None:
    """
    Args:
        role: an affected role that is not a seed.
        seeds: the changed roles.
        count: the variants *role* runs in, at least one.
        roles_path: the roles tree.
        variants: parsed variants per role.

    Returns:
        ``None`` when no round deploys a seed; the bare role id when every
        round does, or when a round's resolution fails, because the
        narrowing cannot be trusted then; else the ``role#i,j`` token.
    """
    try:
        hits = [
            index
            for index in range(count)
            if seeds.intersection(
                _round_resolver(roles_path, role, index, variants).resolve(role)
            )
        ]
    except CombinedResolutionError:
        return role
    if not hits:
        return None
    if len(hits) == count:
        return role
    return role + VARIANT_SEPARATOR + ",".join(str(index) for index in hits)


def affected_selection(changed: Iterable[str]) -> list[str]:
    """
    Args:
        changed: the changed roles.

    Returns:
        Every seed and every role that includes one, transitively, with all
        its variants, and every other
        affected role with only the variants whose round deploys one of
        them; a role none of whose rounds does is left out.
    """
    seeds: set[str] = {r.strip() for r in changed if r and r.strip()}
    affected = affected_roles(changed)
    changed_roles = _with_includers(seeds, _list_role_names())
    variants = get_variants(roles_dir=str(roles_dir()), readonly=True)
    tokens = (
        role
        if role in changed_roles
        else _pinned(
            role,
            changed_roles,
            max(1, len(variants.get(role) or ())),
            roles_dir(),
            variants,
        )
        for role in affected
    )
    return [token for token in tokens if token]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Print every role with a variant whose round deploys one of the "
            "given seed roles, or a role including one, over dependencies or "
            "services, narrowed to those variants. Seed roles and the roles "
            "including them are printed with every variant."
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
