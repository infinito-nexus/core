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

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from utils.cache.applications import get_variants
from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import CONFIG_TOPICS, apply_topic, provider_of
from utils.roles.applications.variant_pins import VariantPinError, resolve_pins
from utils.roles.guide import declares_guide, guide_off
from utils.roles.mapping import ROLE_FILE_META_SERVICES

__all__ = [
    "NestedOverrideConflictError",
    "ResolvedRound",
    "active_variants_for_round",
    "clamped_assignment",
    "collect_provider_overrides",
    "resolve_round",
    "round_under",
    "services_overrides_for_round",
]

_MERGED_SERVICES: dict[tuple[str, int], tuple[tuple[int, int], Any, Any]] = {}


class NestedOverrideConflictError(RuntimeError):
    """Two roles in one round demand different config for one provider."""


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


def _claims(payloads: Mapping[str, Any]) -> list[tuple[str, str, str, Any]]:
    """Return the ``(role, service_key, topic, value)`` a round's payloads carry.

    Args:
        payloads: ``{role: variant payload}`` for one round.

    Reading this before the service registry keeps a round whose variants
    override nothing from paying for the registry at all.
    """
    claims: list[tuple[str, str, str, Any]] = []
    for role_name, payload in payloads.items():
        if not isinstance(payload, Mapping):
            continue
        services = payload.get("services")
        if not isinstance(services, Mapping):
            continue
        for service_key, entry in services.items():
            if not isinstance(entry, Mapping):
                continue
            claims.extend(
                (role_name, service_key, topic, entry[topic])
                for topic in sorted(CONFIG_TOPICS & set(entry))
            )
    return claims


def collect_provider_overrides(
    payloads: Mapping[str, Any], *, roles_dir: str
) -> dict[str, dict[str, Any]]:
    """Return ``{provider: {topic: value}}`` demanded by the round's payloads.

    Args:
        payloads: ``{role: variant payload}`` for one round.
        roles_dir: roles directory the service registry is built from.

    Raises:
        NestedOverrideConflictError: two roles demand different values for the
            same topic of the same provider.
    """
    claims = _claims(payloads)
    if not claims:
        return {}

    registry = build_service_registry_from_roles_dir(Path(roles_dir))
    demanded: dict[str, dict[str, Any]] = {}
    claimed_by: dict[tuple[str, str], str] = {}
    for role_name, service_key, topic, value in claims:
        provider = provider_of(service_key, registry)
        if not provider or provider == role_name:
            continue
        previous = claimed_by.get((provider, topic))
        if previous and demanded[provider][topic] != value:
            raise NestedOverrideConflictError(
                f"{role_name} and {previous} demand different "
                f"{topic!r} for {provider!r} in the same round; a "
                f"round deploys it once, so the two cannot both hold"
            )
        demanded.setdefault(provider, {})[topic] = value
        claimed_by[(provider, topic)] = role_name
    return demanded


def _apply_nested_service_maps(overrides: dict[str, dict], *, roles_dir: str) -> None:
    """Replace a pulled-in provider's services map with what the round demands.

    Only the ``services`` topic reaches this path: the closure walks service
    edges, so the other config topics a variant may override are the inventory
    bake's business.

    Args:
        overrides: ``{role: services map}``, mutated in place.
        roles_dir: roles directory the service registry is built from.
    """
    payloads = {role: {"services": services} for role, services in overrides.items()}
    for provider, topics in collect_provider_overrides(
        payloads, roles_dir=roles_dir
    ).items():
        if "services" not in topics:
            continue
        overrides[provider] = apply_topic(overrides.get(provider), topics["services"])


def _merged_services(services_path: Path, index: int, variant: Mapping) -> Any:
    """Return ``variant`` deep-merged onto ``meta/services.yml``, once per variant.

    An entry is reused only while the file keeps its mtime and size and
    ``variant`` is the very object it was built from, which
    :func:`get_variants` hands out until the variants file changes. The
    result is shared by every round that runs the variant, so nothing
    downstream may mutate it.

    Args:
        services_path: the role's ``meta/services.yml``.
        index: the variant ``variant`` belongs to.
        variant: the variant's ``services`` block.

    Returns:
        The merged map, or ``None`` when the role has no readable
        ``meta/services.yml`` mapping.
    """
    try:
        stat = services_path.stat()
    except OSError:
        return None
    key = (str(services_path), index)
    signature = (stat.st_mtime_ns, stat.st_size)
    hit = _MERGED_SERVICES.get(key)
    if hit is not None and hit[0] == signature and hit[1] is variant:
        return hit[2]
    try:
        base_services = load_yaml_any(services_path) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(base_services, Mapping):
        return None
    merged = _deep_merge(dict(base_services), dict(variant))
    _MERGED_SERVICES[key] = (signature, variant, merged)
    return merged


def _overrides_for_assignment(
    active_index: Mapping[str, int],
    *,
    roles_dir: str,
    primary_app_variants: Mapping[str, int],
    variants_per_app: Mapping[str, list],
) -> dict[str, dict]:
    """Merge each role's assigned variant onto its ``meta/services.yml``.

    Args:
        active_index: role -> the variant index the round runs it in.
        roles_dir: roles directory the services maps are read from.
        primary_app_variants: the round's primary apps; only they keep the
            guide host their variant declares.
        variants_per_app: parsed variants per role.

    Returns:
        ``{role: merged services map}`` for every role with variants and a
        ``meta/services.yml``.
    """
    overrides: dict[str, dict] = {}
    roles_path = Path(roles_dir)
    for role_name, variant_list in variants_per_app.items():
        if not variant_list:
            continue
        index = active_index[role_name]
        variant_payload = variant_list[index]
        if not isinstance(variant_payload, Mapping):
            variant_payload = {}
        variant_services = variant_payload.get("services", {})
        if not isinstance(variant_services, Mapping):
            continue
        merged = _merged_services(
            roles_path / role_name / ROLE_FILE_META_SERVICES, index, variant_services
        )
        if isinstance(merged, dict):
            overrides[role_name] = (
                dict(merged)
                if role_name in primary_app_variants and declares_guide(merged)
                else guide_off(merged)
            )
    _apply_nested_service_maps(overrides, roles_dir=roles_dir)
    return overrides


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
    from cli.administration.deploy.development.inventory import legacy_resolver

    overrides = _overrides_for_assignment(
        active_index,
        roles_dir=roles_dir,
        primary_app_variants=primary_app_variants,
        variants_per_app=variants_per_app,
    )
    include = tuple(
        legacy_resolver._resolve_round_include(
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
    :mod:`utils.roles.applications.variant_pins`). The guide host stays on
    only where a primary app's variant declares it; every other role has
    it off.
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
