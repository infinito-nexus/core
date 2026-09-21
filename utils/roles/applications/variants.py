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
from utils.roles.mapping import ROLE_FILE_META_SERVICES

__all__ = [
    "NestedOverrideConflictError",
    "collect_provider_overrides",
    "services_overrides_for_round",
]


class NestedOverrideConflictError(RuntimeError):
    """Two roles in one round demand different config for one provider."""


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


def services_overrides_for_round(
    *,
    roles_dir: str,
    round_index: int,
    primary_app_variants: Mapping[str, int],
) -> dict[str, dict]:
    """For every role with `meta/variants.yml`, return the services map
    that results from merging the round's variant payload onto the
    role's on-disk `meta/services.yml`.

    Apps in `primary_app_variants` use the supplied (already clamped)
    index. Other roles with their own variants clamp `round_index` to
    their own variant count. Roles without variants are absent from the
    result so the resolver falls through to its disk-read path.

    The merged map is what the inventory ALSO bakes into host_vars, so
    feeding the same dict into `CombinedResolver(services_overrides=...)`
    eliminates the topology-vs-host_vars drift that variant-blind
    resolution produced.
    """
    variants_per_app = get_variants(roles_dir=roles_dir)
    overrides: dict[str, dict] = {}
    roles_path = Path(roles_dir)
    for role_name, variant_list in variants_per_app.items():
        if not variant_list:
            continue
        variant_count = max(1, len(variant_list))
        if role_name in primary_app_variants:
            idx = primary_app_variants[role_name]
        else:
            idx = round_index if round_index < variant_count else 0
        if not 0 <= idx < len(variant_list):
            idx = 0
        variant_payload = variant_list[idx] if variant_list else {}
        if not isinstance(variant_payload, Mapping):
            variant_payload = {}
        variant_services = variant_payload.get("services", {})
        if not isinstance(variant_services, Mapping):
            continue
        services_path = roles_path / role_name / ROLE_FILE_META_SERVICES
        if not services_path.exists():
            continue
        try:
            base_services = load_yaml_any(services_path) or {}
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if not isinstance(base_services, Mapping):
            continue
        merged = _deep_merge(dict(base_services), dict(variant_services))
        if isinstance(merged, dict):
            overrides[role_name] = merged
    _apply_nested_service_maps(overrides, roles_dir=roles_dir)
    return overrides
