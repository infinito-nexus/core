"""Build one role's base `applications.<app>` payload from its `meta/` tree."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .addons import META_ADDONS_DIR, load_addons_dir
from .schema_credentials import extract_default_credentials
from .yaml import load_yaml as _load_yaml_cached
from .yaml import load_yaml_any as _load_yaml_any_cached

if TYPE_CHECKING:
    from pathlib import Path

_CANONICAL_VOLUMES_BY_ROLE: dict[str, dict[str, Any]] = {}

_META_TOPICS: tuple[str, ...] = (
    "server",
    "rbac",
    "services",
    "volumes",
    "csp",
    "domains",
    "networks",
)


_META_NON_GENERIC_TOPICS: frozenset[str] = frozenset(
    {"main", "variants", "volumes", "secrets", "users"}
)


def _has_application_metadata(role_dir: Path) -> bool:
    """Detect whether a role behaves as an application.

    A role is an "application" iff at least one of its `meta/<topic>.yml`
    files exists (plus `meta/secrets.yml` and `meta/users.yml` for the
    schema-only / users-only special cases).
    """
    meta_dir = role_dir / "meta"
    if not meta_dir.is_dir():
        return False
    for topic in _META_TOPICS:
        if (meta_dir / f"{topic}.yml").is_file():
            return True
    if (meta_dir / "secrets.yml").is_file():
        return True
    if (meta_dir / "users.yml").is_file():
        return True
    addons_dir = meta_dir / META_ADDONS_DIR
    return addons_dir.is_dir() and any(addons_dir.glob("*.yml"))


def _assign_nested(root: dict[str, Any], parts: tuple[str, ...], value: Any) -> None:
    """Place *value* at the nested key path *parts* inside *root*, mirroring
    the `meta/` directory layout onto `applications.<app>`: ``("addons", "x")``
    lands at ``root["addons"]["x"]``. A non-dict value already sitting on an
    intermediate segment is replaced by a fresh dict so a deeper file always
    wins its own path.
    """
    node = root
    for key in parts[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[parts[-1]] = value


def _build_role_base_config(
    role_dir: Path,
    roles_dir: Path,
) -> dict[str, Any]:
    """Assemble a role's effective `applications.<app>` payload by walking its
    entire `meta/` tree.

    Every `meta/**/*.yml` maps to `applications.<app>.<relpath>` (directory
    segments become nested keys, the filename stem the leaf), so nested topics
    work without per-topic wiring:

    `meta/server.yml`   → `server`
    `meta/rbac.yml`     → `rbac`
    `meta/services.yml` → `services`
    `meta/info.yml`     → `info`
    `meta/addons/x.yml` → `addons.x`
    `meta/a/b/c.yml`    → `a.b.c`   (any depth)

    Bespoke topics are reshaped instead of placed verbatim:

    `meta/main.yml`, `meta/variants.yml` → skipped (ansible/build mechanism).
    `meta/volumes.yml`  → canonical dict-of-dicts parked in
                         `_CANONICAL_VOLUMES_BY_ROLE` (kept OUT of this payload
                         so its raw Jinja `source:` strings never hit the
                         templar; `get_merged_applications` re-attaches them).
    `meta/addons/*.yml` → `addons` (enable state normalised by
                         `utils.cache.addons.normalize_addons`).
    `meta/secrets.yml`   → `credentials` (only literal `default:` values;
                         non-defaults come from the inventory apply_schema step
                         and are merged in by the caller).
    `meta/users.yml`    → `users` (rewritten to `lookup('users', ...)` so the
                         user-domain cache stays the source of truth).
    Empty role collapses to ``{}`` (no overrides applied).
    """
    from plugins.lookup.application_gid import compute_application_gid

    application_id = role_dir.name
    config_data: dict[str, Any] = {}
    meta_dir = role_dir / "meta"
    if not meta_dir.is_dir():
        return {}

    for path in sorted(meta_dir.rglob("*.yml")):
        parts = path.relative_to(meta_dir).with_suffix("").parts
        if parts[0] == META_ADDONS_DIR:
            continue
        if len(parts) == 1 and parts[0] in _META_NON_GENERIC_TOPICS:
            continue
        data = _load_yaml_cached(path, default_if_missing={})
        if data:
            _assign_nested(config_data, parts, data)

    volumes_data = _load_yaml_any_cached(
        meta_dir / "volumes.yml", default_if_missing={}
    )
    if isinstance(volumes_data, dict) and volumes_data:
        _CANONICAL_VOLUMES_BY_ROLE[role_dir.name] = volumes_data

    addons_data = load_addons_dir(meta_dir)
    if addons_data:
        config_data["addons"] = addons_data

    schema_data = _load_yaml_cached(meta_dir / "secrets.yml", default_if_missing={})
    if schema_data:
        creds_defaults = extract_default_credentials(
            schema_data.get("credentials") or {}
        )
        if creds_defaults:
            config_data.setdefault("secrets", {})["credentials"] = creds_defaults

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
