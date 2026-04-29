"""Application-domain cache: variants, defaults, merged lookup.

Owns `_APPLICATIONS_DEFAULTS_CACHE`, `_VARIANTS_CACHE`, and
`_MERGED_APPLICATIONS_CACHE`. Public API: `get_application_defaults`,
`get_variants`, `get_merged_applications`. Strictly ansible-free at
import time so the GitHub Actions runner-host CLI path
(`cli.deploy.development.init` -> `plan_dev_inventory_matrix` ->
`get_variants`) keeps working without ansible installed.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from plugins.filter.merge_with_defaults import merge_with_defaults

from .base import (
    _RENDER_GUARD,
    _cache_key,
    _deep_merge,
    _render_with_templar,
    _resolve_override_mapping,
    _resolve_roles_dir,
    _stable_variables_signature,
)
from .yaml import load_yaml as _load_yaml_cached
from .yaml import load_yaml_any as _load_yaml_any_cached


_APPLICATIONS_DEFAULTS_CACHE: dict[str, dict[str, Any]] = {}
_VARIANTS_CACHE: dict[str, dict[str, list[Any]]] = {}
_MERGED_APPLICATIONS_CACHE: dict[tuple, dict[str, Any]] = {}

# Per req-008, every role's metadata lives under these `meta/<topic>.yml`
# files. The file root IS the value of `applications.<app>.<topic>` — there
# is NO wrapping key matching the filename.
_META_TOPICS: tuple[str, ...] = ("server", "rbac", "services", "volumes")

# `meta/info.yml` is descriptive role-level metadata (req-011). Loaded into
# `applications.<role>.info` like the other meta files, but does NOT mark a
# role as an application by itself — a metadata-only `info.yml` next to a
# bare `meta/main.yml` is just documentation, not config.
_META_INFO_TOPIC: str = "info"


def _extract_default_credentials(creds_node: Any) -> dict[str, Any]:
    """Walk a `meta/schema.yml` `credentials:` tree and return the subset of
    leaves that carry a literal `default:` Jinja string.

    The shape mirrors the schema tree: nested keys stay nested. Per req-008
    the literal string is preserved verbatim — no rendering, no validation.
    Leaves WITHOUT `default:` are intentionally absent so the inventory's
    apply_schema-generated values win the merge.
    """
    if not isinstance(creds_node, Mapping):
        return {}

    is_leaf = any(
        marker in creds_node
        for marker in ("default", "algorithm", "validation", "description")
    )
    if is_leaf:
        return {}

    out: dict[str, Any] = {}
    for key, value in creds_node.items():
        if not isinstance(value, Mapping):
            continue
        leaf = any(
            marker in value
            for marker in ("default", "algorithm", "validation", "description")
        )
        if leaf:
            if "default" in value:
                out[key] = value["default"]
        else:
            nested = _extract_default_credentials(value)
            if nested:
                out[key] = nested
    return out


def _has_application_metadata(role_dir: Path) -> bool:
    """Detect whether a role behaves as an application after req-008.

    A role is an "application" iff at least one of its `meta/<topic>.yml`
    files exists (plus `meta/schema.yml` and `meta/users.yml` for the
    schema-only / users-only special cases). Replaces the legacy
    `roles/<role>/meta/services.yml`-presence test.
    """
    meta_dir = role_dir / "meta"
    if not meta_dir.is_dir():
        return False
    for topic in _META_TOPICS:
        if (meta_dir / f"{topic}.yml").is_file():
            return True
    if (meta_dir / "schema.yml").is_file():
        return True
    if (meta_dir / "users.yml").is_file():
        return True
    return False


def _build_role_base_config(
    role_dir: Path,
    roles_dir: Path,
) -> dict[str, Any]:
    """Assemble a role's effective `applications.<app>` payload from its
    `meta/<topic>.yml` files.

    `meta/server.yml`   → `server`
    `meta/rbac.yml`     → `rbac`
    `meta/services.yml` → `services`
    `meta/volumes.yml`  → `volumes`
    `meta/info.yml`     → `info`     (descriptive role-level metadata per req-011)
    `meta/schema.yml`   → `credentials` (only the literal `default:` values;
                         non-default credentials are filled by the
                         inventory's apply_schema step and merged in by the
                         caller).
    `meta/users.yml`    → `users` (rewritten to `lookup('users', ...)` so the
                         user-domain cache stays the source of truth).
    Empty role collapses to ``{}`` (no overrides applied).
    """
    # Pure-Python GID resolver — does NOT pull ansible. The previous
    # `ApplicationGidLookup().run([...])` call dragged
    # `ansible.plugins.lookup.LookupBase` into this code path and broke
    # `cli.deploy.development init` on the GitHub Actions runner host
    # (CI run 24935979190) where the runner Python ships without
    # ansible. The split lives in plugins/lookup/application_gid.py:
    # `compute_application_gid` is the pure helper, `LookupModule` is
    # the ansible-facing wrapper.
    from plugins.lookup.application_gid import compute_application_gid

    application_id = role_dir.name
    config_data: dict[str, Any] = {}
    meta_dir = role_dir / "meta"

    for topic in _META_TOPICS:
        topic_data = _load_yaml_cached(meta_dir / f"{topic}.yml", default_if_missing={})
        if topic_data:
            config_data[topic] = topic_data

    info_data = _load_yaml_cached(
        meta_dir / f"{_META_INFO_TOPIC}.yml", default_if_missing={}
    )
    if info_data:
        config_data[_META_INFO_TOPIC] = info_data

    schema_data = _load_yaml_cached(meta_dir / "schema.yml", default_if_missing={})
    if schema_data:
        creds_defaults = _extract_default_credentials(
            schema_data.get("credentials") or {}
        )
        if creds_defaults:
            config_data["credentials"] = creds_defaults

    users_meta = _load_yaml_cached(meta_dir / "users.yml", default_if_missing={})
    if isinstance(users_meta, dict) and users_meta:
        config_data["users"] = {
            user_key: "{{ lookup('users', " + repr(user_key) + ") }}"
            for user_key in users_meta
        }

    if not config_data:
        return {}

    config_data["group_id"] = compute_application_gid(application_id, str(roles_dir))
    return config_data


def _iter_application_role_dirs(roles_dir: Path):
    """Yield application role directories in deterministic alphabetical order."""
    for child in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if _has_application_metadata(child):
            yield child


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
        raise ValueError(
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

    for role_dir in _iter_application_role_dirs(roles_dir):
        application_id = role_dir.name
        base_config = _build_role_base_config(role_dir, roles_dir)
        meta_path = role_dir / "meta" / "variants.yml"
        override_list = _load_variants_overrides(meta_path)
        role_variants: list[Any] = []
        for override in override_list:
            if base_config:
                role_variants.append(_deep_merge(base_config, override))
            else:
                # Role has no meta payload, but a variant list MAY still
                # legitimately produce an override-only result. Fall back
                # to a deep copy of the override so callers never observe
                # shared mutable state.
                role_variants.append(copy.deepcopy(override))
        variants[application_id] = role_variants

    return {key: variants[key] for key in sorted(variants)}


def _build_application_defaults(roles_dir: Path) -> dict[str, Any]:
    """Backward-compatible shim: every consumer that historically saw
    one mapping per application now sees the FIRST variant (index 0).
    The full list is exposed via :func:`get_variants`."""
    return {
        application_id: copy.deepcopy(variant_list[0])
        for application_id, variant_list in _build_variants(roles_dir).items()
    }


def get_application_defaults(
    *, roles_dir: Optional[str | os.PathLike[str]] = None
) -> dict[str, Any]:
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _APPLICATIONS_DEFAULTS_CACHE.get(key)
    if cached is None:
        cached = _build_application_defaults(resolved_roles_dir)
        _APPLICATIONS_DEFAULTS_CACHE[key] = cached
    return copy.deepcopy(cached)


def get_variants(
    *, roles_dir: Optional[str | os.PathLike[str]] = None
) -> dict[str, list[Any]]:
    """Return ``{application_id: [variant_0, ...]}`` cached per
    ``roles_dir``. Each variant is the role's effective configuration
    after the corresponding `meta/variants.yml` override has been
    deep-merged on top of `meta/services.yml`."""
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _VARIANTS_CACHE.get(key)
    if cached is None:
        cached = _build_variants(resolved_roles_dir)
        _VARIANTS_CACHE[key] = cached
    return copy.deepcopy(cached)


def get_merged_applications(
    *,
    variables: Optional[dict[str, Any]] = None,
    roles_dir: Optional[str | os.PathLike[str]] = None,
    templar: Any = None,
) -> dict[str, Any]:
    # Late import: `get_merged_users` lives in the sibling `users` module
    # and pulls user-domain machinery (token store, alias materialization,
    # etc.) that this module's other entry points don't need. Importing
    # at function scope keeps `import utils.cache.applications` cheap so
    # the runner-host CLI path can use `get_variants` without paying for
    # the user-domain transitive imports.
    from .users import get_merged_users

    variables = variables or {}
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    cache_key = (
        _cache_key(resolved_roles_dir),
        _stable_variables_signature(variables),
    )
    cached = _MERGED_APPLICATIONS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Defaults always come from variant 0 (= the legacy `meta/services.yml`
    # payload, deep-merged with the empty `{}` entry). Per-round variant
    # overrides are baked into the inventory's `applications.<app>` block at
    # init time (see `cli.deploy.development.inventory.build_dev_inventory`)
    # and applied below as overrides on top of these defaults, so the deploy
    # stage needs no runtime variant selector: the inventory itself is
    # variant-resolved.
    defaults = get_application_defaults(roles_dir=resolved_roles_dir)

    overrides = _resolve_override_mapping(variables, "applications", templar=templar)

    merged = merge_with_defaults(defaults, overrides)

    if getattr(_RENDER_GUARD, "applications", False):
        # Re-entry via cross-lookup: return unrendered merged payload; the
        # outer templar will resolve remaining Jinja at use-site.
        return merged

    _RENDER_GUARD.applications = True
    try:
        raw_users = get_merged_users(
            variables=variables,
            roles_dir=roles_dir,
            templar=None,
        )
        rendered = _render_with_templar(
            merged,
            templar=templar,
            variables=variables,
            raw_applications=merged,
            raw_users=raw_users,
        )
    finally:
        _RENDER_GUARD.applications = False

    _MERGED_APPLICATIONS_CACHE[cache_key] = rendered
    return rendered


def _reset() -> None:
    _APPLICATIONS_DEFAULTS_CACHE.clear()
    _VARIANTS_CACHE.clear()
    _MERGED_APPLICATIONS_CACHE.clear()
