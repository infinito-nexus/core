"""Variant payload baking for the development inventory.

Two helpers, both pure: `_resolve_variant_payloads` picks the variant
payload for each app in a round's include set, and `_bake_overrides`
merges those payloads under `applications:` inside the `--vars` JSON
the inventory provision step consumes. Caller-supplied `extra_vars`
always win over the variant bake — that's the documented "user vars
always win" rule.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from utils.cache.applications import get_variant_overrides_only
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import apply_topic, provider_of
from utils.roles.applications.variants import collect_provider_overrides
from utils.roles.guide import GUIDE_SERVICE_KEY, without_guide


def _guide_services(payload: Any) -> Mapping[str, Any] | None:
    services = payload.get("services") if isinstance(payload, Mapping) else None
    if isinstance(services, Mapping) and GUIDE_SERVICE_KEY in services:
        return services
    return None


def _drop_undeployed_guide(
    resolved: dict[str, Any], *, roles_dir: str, include: Sequence[str]
) -> dict[str, Any]:
    if not any(_guide_services(payload) for payload in resolved.values()):
        return resolved
    registry = build_service_registry_from_roles_dir(Path(roles_dir))
    if provider_of(GUIDE_SERVICE_KEY, registry) in include:
        return resolved
    stripped: dict[str, Any] = {}
    for app_id, payload in resolved.items():
        services = _guide_services(payload)
        stripped[app_id] = (
            payload
            if services is None
            else {**payload, "services": without_guide(services)}
        )
    return stripped


def _resolve_variant_payloads(
    *,
    roles_dir: str,
    include: Sequence[str],
    active_variants: Mapping[str, int],
) -> dict[str, Any]:
    """Return ``{app_id: variant_override}`` for the requested round.

    Each value is the raw `meta/variants.yml` entry — NOT the
    deep-merge of variants.yml on top of `meta/services.yml`. Baking
    only the override keeps host_vars sparse so downstream passes
    (notably `apply_mirror_overrides`) can populate fields like
    `image`/`version` that the role declares in `meta/services.yml`.

    Apps without `meta/variants.yml` collapse to a single empty
    override `{}`. Out-of-range indices clamp to 0.

    A config topic a variant declares under a service it depends on is
    finally moved onto that service's provider, so the role pulling a
    dependency in is what decides how lean the dependency runs.

    A guide host entry is baked only while the round deploys the guide
    host itself.
    """
    overrides_per_app = get_variant_overrides_only(roles_dir=roles_dir)
    resolved: dict[str, Any] = {}
    for app_id in include:
        variant_list = overrides_per_app.get(app_id) or [{}]
        if not variant_list:
            continue
        index = active_variants.get(app_id, 0)
        if not 0 <= index < len(variant_list):
            index = 0
        resolved[app_id] = variant_list[index]
    resolved = _drop_undeployed_guide(resolved, roles_dir=roles_dir, include=include)
    for provider, topics in collect_provider_overrides(
        resolved, roles_dir=roles_dir
    ).items():
        if provider not in resolved:
            continue
        payload = resolved[provider]
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        for topic, value in topics.items():
            payload[topic] = apply_topic(payload.get(topic), value)
        resolved[provider] = payload
    return resolved


def _bake_overrides(
    *,
    base_overrides: Mapping[str, Any],
    variant_payloads: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge the per-app variant payloads under `applications:` into the
    `--vars` JSON the init step will hand to
    `infinito administration inventory provision`.
    Caller-supplied `extra_vars` (already inside `base_overrides`) win
    over the variant bake when the same key is set on both sides — that
    matches the existing "user vars always win" rule."""
    merged: dict[str, Any] = dict(base_overrides)
    if not variant_payloads:
        return merged
    existing_apps = merged.get("applications")
    if not isinstance(existing_apps, Mapping):
        existing_apps = {}
    apps: dict[str, Any] = dict(variant_payloads.items())
    for app_id, override in existing_apps.items():
        base_payload = apps.get(app_id)
        if isinstance(base_payload, Mapping) and isinstance(override, Mapping):
            apps[app_id] = {**base_payload, **override}
        else:
            apps[app_id] = override
    merged["applications"] = apps
    return merged
