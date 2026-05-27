"""Pure validation helpers shared by the `tests/integration/lookups/config`
test modules. Kept separate from `_scan.py` so each test class wires
exactly the helpers it needs."""

from __future__ import annotations

import fnmatch
from collections.abc import Mapping
from typing import Any


class PathNotFoundError(Exception):
    """Raised by helpers when a dotted path does not resolve."""


def assert_nested(mapping: Mapping[str, Any], dotted: str, context: str) -> None:
    """Walk ``dotted`` through ``mapping``; raise ``PathNotFoundError`` on miss."""
    keys = dotted.split(".")
    cur: Any = mapping
    for k in keys:
        if not isinstance(cur, Mapping):
            raise PathNotFoundError(f"{context}: expected dict at {k}")
        if k not in cur:
            raise PathNotFoundError(f"{context}: missing '{k}' in '{dotted}'")
        cur = cur[k]


def match_wildcard_segment(mapping: Any, segment: str) -> bool:
    """Return True when ``segment`` matches at least one top-level key.

    ``segment`` may contain ``*`` glob characters; bare ``*`` matches any
    key.
    """
    if not isinstance(mapping, Mapping):
        return False
    if "*" not in segment:
        return segment in mapping
    return any(fnmatch.fnmatchcase(k, segment) for k in mapping)


def match_wildcard_path(mapping: Any, dotted: str) -> bool:
    """Return True when ``dotted`` matches at least one nested path in
    ``mapping``. Each segment may be a literal key, a bare ``*``
    (matches any single key), or a glob containing ``*`` (matches any
    key whose name matches the glob, e.g. ``*_jwt_secret``)."""
    keys = dotted.split(".")

    def walk(cur: Any, idx: int) -> bool:
        if idx == len(keys):
            return True
        if not isinstance(cur, Mapping):
            return False
        key = keys[idx]
        if "*" not in key:
            return key in cur and walk(cur[key], idx + 1)
        return any(
            fnmatch.fnmatchcase(child_key, key) and walk(child_val, idx + 1)
            for child_key, child_val in cur.items()
        )

    return walk(mapping, 0)


def validate_app_path(
    application_defaults: dict[str, Any],
    role_schemas: dict[str, dict[str, Any]],
    user_defaults: dict[str, Any],
    app_id: str,
    dotted: str,
) -> None:
    """Resolve ``dotted`` against the same fallback chain the runtime
    plugin uses: app defaults → users → credentials in defaults →
    credentials in schema → images presence. Raise ``PathNotFoundError`` on
    a final miss."""
    cfg = application_defaults.get(app_id, {})
    try:
        assert_nested(cfg, dotted, app_id)
    except PathNotFoundError:
        pass
    else:
        return
    if dotted.startswith("users."):
        sub = dotted.split(".", 1)[1]
        if sub in user_defaults:
            return
    if dotted.startswith("credentials."):
        key = dotted.split(".", 1)[1]
        creds_cfg = cfg.get("credentials", {}) if isinstance(cfg, Mapping) else {}
        if isinstance(creds_cfg, Mapping) and key in creds_cfg:
            return
        schema = role_schemas.get(app_id, {})
        creds = schema.get("credentials", {}) if isinstance(schema, Mapping) else {}
        if isinstance(creds, Mapping) and key in creds:
            return
        raise PathNotFoundError(f"Credential '{key}' missing for app '{app_id}'")
    if dotted.startswith("images.") and isinstance(cfg.get("images"), Mapping):
        return
    raise PathNotFoundError(f"'{dotted}' not found for '{app_id}'")
