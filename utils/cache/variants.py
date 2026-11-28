"""Variant cache: each role's `meta/variants.yml` merged onto its base config.

Strictly ansible-free at import time, like `utils.cache.applications`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from utils.roles.applications.mcp import derive_mcp_presence
from utils.roles.mapping import ROLE_FILE_META_VARIANTS

from .base import _cache_key, _deep_merge, _resolve_roles_dir
from .role_config import _build_role_base_config, _iter_application_role_dirs
from .yaml import load_yaml_any as _load_yaml_any_cached

if TYPE_CHECKING:
    import os
    from pathlib import Path

_VARIANTS_CACHE: dict[str, dict[str, list[Any]]] = {}
_VARIANT_OVERRIDES_ONLY_CACHE: dict[str, dict[str, list[dict[str, Any]]]] = {}


def _load_variants_overrides(path: Path) -> list[dict[str, Any]]:
    """Load a `roles/<role>/meta/variants.yml` variant list through the
    shared YAML cache.

    Each entry is a deep-merge override for the role's
    `meta/services.yml`; ``null`` and ``{}`` are valid no-op entries.
    Missing file or empty list collapses to a single empty variant so
    the role keeps its pre-variant behaviour.
    """
    if not path.exists():
        return [{}]

    raw = _load_yaml_any_cached(path)
    if raw in (None, {}):
        return [{}]
    if not isinstance(raw, list):
        raise TypeError(
            f"{path} must contain a YAML list of override mappings (or be empty)."
        )
    if not raw:
        return [{}]

    normalised: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if entry is None:
            normalised.append({})
        elif isinstance(entry, Mapping):
            normalised.append(dict(entry))
        else:
            raise ValueError(
                f"{path}[{index}] must be a mapping (or null); got {type(entry).__name__}"
            )
    return normalised


def _build_variants(roles_dir: Path) -> dict[str, list[Any]]:
    """Return ``{application_id: [variant_0, variant_1, ...]}``.

    Each variant is the role's assembled `meta/<topic>.yml` payload
    deep-merged with the corresponding entry from
    `roles/<role>/meta/variants.yml`. A missing/empty `meta/variants.yml`
    collapses to a single empty variant so the role keeps its pre-variant
    behaviour.
    """
    variants: dict[str, list[Any]] = {}
    bases: dict[str, Any] = {}

    for role_dir in _iter_application_role_dirs(roles_dir):
        application_id = role_dir.name
        base_config = _build_role_base_config(role_dir, roles_dir)
        bases[application_id] = base_config
        meta_path = role_dir / ROLE_FILE_META_VARIANTS
        override_list = _load_variants_overrides(meta_path)
        role_variants: list[Any] = []
        for override in override_list:
            if base_config:
                role_variants.append(_deep_merge(base_config, override))
            else:
                role_variants.append(copy.deepcopy(override))
        variants[application_id] = role_variants

    derive_mcp_presence(bases)
    for application_id, role_variants in variants.items():
        derived = (bases.get(application_id) or {}).get("mcp")
        if not isinstance(derived, dict):
            continue
        for variant_config in role_variants:
            block = (
                variant_config.get("mcp") if isinstance(variant_config, dict) else None
            )
            if isinstance(block, dict):
                block.setdefault("enabled", derived["enabled"])
                block.setdefault("shared", derived["shared"])

    return {key: variants[key] for key in sorted(variants)}


def get_variants(
    *, roles_dir: str | os.PathLike[str] | None = None, readonly: bool = False
) -> dict[str, list[Any]]:
    """Return ``{application_id: [variant_0, ...]}`` cached per
    ``roles_dir``. Each variant is the role's effective configuration
    after the corresponding `meta/variants.yml` override has been
    deep-merged on top of `meta/services.yml`.

    Args:
        roles_dir: roles tree to read, defaulting to the project's own.
        readonly: hand out the cached structure itself instead of a deep
            copy. The copy is what keeps one caller's mutation out of every
            later caller's data, so this is only for a caller that provably
            reads: a sweep resolves hundreds of rounds, and copying the whole
            map per round costs more than building it once did.
    """
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _VARIANTS_CACHE.get(key)
    if cached is None:
        cached = _build_variants(resolved_roles_dir)
        _VARIANTS_CACHE[key] = cached
    return cached if readonly else copy.deepcopy(cached)


def with_variants(
    applications: Mapping[str, Any],
    available: Mapping[str, list[Any]],
    variants: Mapping[str, int],
) -> dict[str, Any]:
    """Return applications with every app of variants swapped to that variant.

    Args:
        applications: the base configurations, left untouched.
        available: the `get_variants` map of the same roles tree.
        variants: per-app variant index; an index the app does not declare
            keeps its base configuration.
    """
    result = dict(applications)
    for app_id, index in variants.items():
        app_variants = available.get(app_id) or []
        if 0 <= index < len(app_variants):
            result[app_id] = app_variants[index]
    return result


def _build_variant_overrides_only(
    roles_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    overrides: dict[str, list[dict[str, Any]]] = {}
    for role_dir in _iter_application_role_dirs(roles_dir):
        meta_path = role_dir / ROLE_FILE_META_VARIANTS
        overrides[role_dir.name] = _load_variants_overrides(meta_path)
    return {key: overrides[key] for key in sorted(overrides)}


def get_variant_overrides_only(
    *, roles_dir: str | os.PathLike[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{application_id: [override_0, ...]}``, the raw
    `meta/variants.yml` entries per role WITHOUT deep-merging
    `meta/services.yml`.

    Used by matrix-deploy's `--vars` bake so the host_vars payload
    stays sparse: only the variant-specific overrides land there,
    leaving `meta/services.yml` fields (notably `image`/`version`)
    blank in host_vars so `apply_mirror_overrides` can populate them
    from `mirrors.yml`.
    """
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _VARIANT_OVERRIDES_ONLY_CACHE.get(key)
    if cached is None:
        cached = _build_variant_overrides_only(resolved_roles_dir)
        _VARIANT_OVERRIDES_ONLY_CACHE[key] = cached
    return copy.deepcopy(cached)
