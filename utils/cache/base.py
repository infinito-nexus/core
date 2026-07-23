"""Cross-cutting helpers for the `utils.cache.*` package.

Holds primitives that the domain modules (`users`, `applications`,
`domains`) all need but no domain owns: filesystem constants, YAML
loaders, deep-merge, cache-key + content-fingerprint signatures,
templar-render machinery, and the cross-domain re-entry guard.

Stays import-cheap so that `utils.cache.applications` (consumed on
GitHub Actions runner hosts that ship without ansible — see CI runs
24934007615 / 24935979190) can pull this module without dragging
ansible in. The single ansible-coupled symbol exposed from here is
`_render_with_templar`, which lazy-imports `utils.templating.ansible`
only when actually invoked.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plugins.filter.merge.with_defaults import (
    merge_with_defaults,  # noqa: F401  re-exported
)
from utils.paths import FILE_TOKENS

from . import PROJECT_ROOT, ROLES_DIR  # noqa: F401

if TYPE_CHECKING:
    import os

try:
    from ansible.parsing.vault import EncryptedString as _AnsibleEncryptedString
except Exception:
    _AnsibleEncryptedString = None


def _decrypt_ansible_encrypted_strings(value: Any) -> Any:
    """Recursively convert Ansible EncryptedString values to plaintext str.

    Ansible 2.19+ refuses to store EncryptedString as an intermediate variable
    during task arg finalization, so decrypt at the lookup boundary.
    """
    if _AnsibleEncryptedString is not None and isinstance(
        value, _AnsibleEncryptedString
    ):
        try:
            return str(value)
        except Exception:
            return value
    if isinstance(value, Mapping):
        return {k: _decrypt_ansible_encrypted_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decrypt_ansible_encrypted_strings(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_decrypt_ansible_encrypted_strings(v) for v in value)
    return value


DEFAULT_TOKENS_FILE = FILE_TOKENS


_RENDER_GUARD = threading.local()


_FINGERPRINT_BY_ID: dict[int, str] = {}


def _cache_key(roles_dir: Path) -> str:
    return str(roles_dir.resolve())


def _fingerprint_mapping(obj: Any) -> str:
    """Cheap-ish content fingerprint for cache keying.

    Ansible 2.19+ composes a fresh `variables` mapping per task via
    VariableManager.get_vars() and — empirically — often reconstructs the
    inventory-level `applications`/`users` dicts too, so keying on `id(obj)`
    misses the cache across tasks. A content fingerprint hits across tasks
    whenever the inventory payload is unchanged.

    Fast path: id()-keyed memo (within a single task the same dict instance is
    typically reused for multiple lookups, so we avoid re-hashing).
    Slow path: repr-based MD5. Non-mapping values collapse to an "id:..." tag
    so we don't accidentally collide across unrelated types.
    """
    if obj is None:
        return "0"
    obj_id = id(obj)
    cached = _FINGERPRINT_BY_ID.get(obj_id)
    if cached is not None:
        return cached
    try:
        import hashlib

        data = repr(sorted(obj.items())) if isinstance(obj, Mapping) else repr(obj)
        digest = hashlib.md5(
            data.encode("utf-8", errors="replace"),
            usedforsecurity=False,
        ).hexdigest()
    except Exception:
        digest = f"id:{obj_id}"
    _FINGERPRINT_BY_ID[obj_id] = digest
    return digest


def _stable_variables_signature(variables: Mapping[str, Any] | None) -> tuple:
    """Build a content-based cache signature from the subset of `variables`
    that influences the merged applications/users payload.

    See `_fingerprint_mapping` for why id()-only keys don't work reliably.
    """
    if not variables:
        return ("0", "0", "", "")
    return (
        _fingerprint_mapping(variables.get("applications")),
        _fingerprint_mapping(variables.get("users")),
        str(variables.get("DOMAIN_PRIMARY") or ""),
        str(variables.get("SYSTEM_EMAIL_DOMAIN") or ""),
    )


def _tokens_file_signature(path: Path) -> tuple:
    """Return a cheap stat-based signature for the tokens file.

    The merged-users cache must invalidate whenever sys-token-store persists a
    new token — otherwise downstream `lookup('users', ...)` returns stale tokens
    within the same play. stat() is cheap and captures in-place writes.
    """
    try:
        st = path.stat()
    except (FileNotFoundError, OSError):
        return (str(path), 0, 0)
    return (str(path), st.st_mtime_ns, st.st_size)


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = {k: copy.deepcopy(v) for k, v in base.items()}
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def _resolve_roles_dir(*, roles_dir: str | os.PathLike[str] | None = None) -> Path:
    return Path(roles_dir).resolve() if roles_dir else ROLES_DIR.resolve()


def _resolve_override_mapping(
    variables: Mapping[str, Any] | None,
    key: str,
    templar: Any = None,
) -> dict[str, Any]:
    """Return runtime override mappings defensively.

    Nested `lookup('template', ...)` renders sometimes expose top-level lookup
    inputs like `applications`/`users` as non-mapping placeholder values instead
    of the original inventory overrides. Try to coerce via templar before
    falling back to aggregated defaults.
    """

    variables = variables or {}
    value = variables.get(key, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping) and templar is not None:
        try:
            rendered = templar.template(value, fail_on_undefined=False)
        except TypeError:
            try:
                rendered = templar.template(value)
            except Exception:
                rendered = value
        except Exception:
            rendered = value
        if isinstance(rendered, Mapping):
            value = rendered
    if not isinstance(value, Mapping):
        raw_key = {
            "applications": "_INFINITO_APPLICATIONS_RAW",
            "users": "_INFINITO_USERS_RAW",
        }.get(key)
        if raw_key:
            raw = variables.get(raw_key)
            if isinstance(raw, Mapping):
                value = raw
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _render_with_templar(
    value: Any,
    *,
    templar: Any,
    variables: dict[str, Any] | None,
    raw_applications: dict[str, Any] | None = None,
    raw_users: dict[str, Any] | None = None,
    max_rounds: int = 4,
) -> Any:
    if templar is None:
        return value

    from utils.templating.ansible import _templar_render_best_effort

    prev_templar_avail = getattr(templar, "available_variables", None)
    base_variables: dict[str, Any] = (
        dict(prev_templar_avail) if prev_templar_avail else {}
    )
    if variables:
        base_variables.update(variables)
    if raw_applications is not None:
        base_variables["_INFINITO_APPLICATIONS_RAW"] = raw_applications
    if raw_users is not None:
        base_variables["_INFINITO_USERS_RAW"] = raw_users

    def _render_scalar(raw: Any) -> Any:
        if isinstance(raw, str) and "{{" not in raw and "{%" not in raw:
            return raw
        data = copy.deepcopy(raw)
        if isinstance(data, str):
            stripped = data.strip()
            if (
                stripped.startswith("{{")
                and stripped.endswith("}}")
                and "{{" not in stripped[2:]
                and "{%" not in stripped
            ):
                from utils.templating.ansible import _templar_render_preserve_type

                try:
                    rendered = _templar_render_preserve_type(
                        templar, data, base_variables
                    )
                except Exception:
                    rendered = None
                if rendered is not None and not isinstance(rendered, str):
                    return _render_deep(rendered)
            for _ in range(max_rounds):
                try:
                    rendered = _templar_render_best_effort(
                        templar, data, base_variables
                    )
                except Exception:
                    return data
                if rendered == data:
                    break
                data = rendered
            return data

        for _ in range(max_rounds):
            try:
                rendered = templar.template(data, fail_on_undefined=False)
            except TypeError:
                rendered = templar.template(data)
            except Exception:
                return data
            if rendered == data:
                break
            data = rendered
        return data

    def _render_deep(raw: Any) -> Any:
        if isinstance(raw, Mapping):
            return {key: _render_deep(item) for key, item in raw.items()}
        if isinstance(raw, list):
            return [_render_deep(item) for item in raw]
        if isinstance(raw, tuple):
            return tuple(_render_deep(item) for item in raw)
        return _render_scalar(raw)

    try:
        if hasattr(templar, "available_variables"):
            templar.available_variables = base_variables
        data = _render_deep(value)
    finally:
        if hasattr(templar, "available_variables"):
            templar.available_variables = prev_templar_avail

    return _decrypt_ansible_encrypted_strings(data)


def _reset() -> None:
    """Clear the per-process content-fingerprint memo. Domain modules
    own their own caches and provide their own `_reset()`; this one
    only owns `_FINGERPRINT_BY_ID`. The facade `data._reset_cache_for_tests`
    orchestrates all four resets."""
    _FINGERPRINT_BY_ID.clear()
