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
from typing import Any

from utils.cache.applications import get_variant_overrides_only


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
    # Caller-supplied `applications.*` entries deep-overlay the variant
    # payload so overrides like `applications.web-app-foo.feature_flag` from
    # `--vars` still take precedence.
    for app_id, override in existing_apps.items():
        base_payload = apps.get(app_id)
        if isinstance(base_payload, Mapping) and isinstance(override, Mapping):
            apps[app_id] = {**base_payload, **override}
        else:
            apps[app_id] = override
    merged["applications"] = apps
    return merged
