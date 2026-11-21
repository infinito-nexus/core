from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from utils.cache.base import _deep_merge
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import CONFIG_TOPICS, apply_topic, provider_of
from utils.roles.guide import GUIDE_SERVICE_KEY
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SEMAPHORE_SERVICE_KEY = "semaphore"

PRIMARY_ONLY_SERVICE_KEYS: tuple[str, ...] = (GUIDE_SERVICE_KEY, SEMAPHORE_SERVICE_KEY)
"""Hosts every invokable role declares, each gated on the host's own group.

Walked as ordinary consumer edges, those gates would pull the guide host and
Semaphore into every round. A round keeps such an edge only on a primary app
whose resolved services switch it on as a literal ``true``; the host's own
rounds still deploy it, because a primary app is always part of its round."""

_MERGED_SERVICES: dict[tuple[str, int], tuple[tuple[int, int], Any, Any]] = {}


class NestedOverrideConflictError(RuntimeError):
    """Two roles in one round demand different config for one provider."""


def primary_only(services: Mapping[str, Any], *, primary: bool) -> dict[str, Any]:
    """``services`` with every primary-only host edge switched off, except
    where a primary app declares it as a literal ``true``.

    Args:
        services: a role's resolved services map.
        primary: whether the role is a primary app of the round.
    """
    result = dict(services)
    for key in PRIMARY_ONLY_SERVICE_KEYS:
        entry = result.get(key)
        if not isinstance(entry, Mapping):
            continue
        if primary and entry.get("enabled") is True:
            continue
        result[key] = {**entry, "enabled": False, "shared": False}
    return result


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


def overrides_for_assignment(
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
            primary-only hosts their variant declares.
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
            overrides[role_name] = primary_only(
                merged, primary=role_name in primary_app_variants
            )
    _apply_nested_service_maps(overrides, roles_dir=roles_dir)
    return overrides
