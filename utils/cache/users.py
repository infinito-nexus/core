"""User-domain cache: defs, hydration, materialization, merged lookup.

Owns `_USERS_DEFAULTS_CACHE` and `_MERGED_USERS_CACHE`. Public API:
`get_user_defaults`, `get_merged_users`. The Ansible-facing `users`
lookup plugin consumes `get_merged_users` directly from this module
(`from utils.cache.users import get_merged_users`).
"""

from __future__ import annotations

import copy
import glob
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlparse


from . import base as _base
from .base import (
    _RENDER_GUARD,
    _cache_key,
    _deep_merge,
    _render_with_templar,
    _resolve_override_mapping,
    _resolve_roles_dir,
    _stable_variables_signature,
    _tokens_file_signature,
)
from .yaml import load_yaml as _load_yaml_cached


_USERS_DEFAULTS_CACHE: dict[str, dict[str, Any]] = {}
_MERGED_USERS_CACHE: dict[tuple, dict[str, Any]] = {}


def _merge_users(
    defaults: Mapping[str, Any],
    overrides: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    merged = {key: copy.deepcopy(value) for key, value in defaults.items()}
    for key, value in (overrides or {}).items():
        merged[key] = _deep_merge(merged.get(key, {}), value)
    return merged


def _compute_reserved_usernames(roles_dir: Path) -> list[str]:
    reserved: set[str] = set()
    for role_dir in roles_dir.iterdir():
        if not role_dir.is_dir():
            continue
        candidate = role_dir.name.rsplit("-", 1)[-1]
        if candidate.isalnum() and candidate.islower():
            reserved.add(candidate)
    return sorted(reserved)


def _load_user_defs(roles_dir: Path) -> OrderedDict[str, dict[str, Any]]:
    pattern = os.path.join(str(roles_dir), "*/meta/users.yml")
    files = sorted(glob.glob(pattern))
    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for filepath in files:
        users = _load_yaml_cached(Path(filepath), default_if_missing={})
        if not isinstance(users, dict):
            continue

        for key, overrides in users.items():
            if not isinstance(overrides, dict):
                raise ValueError(f"Invalid definition for user '{key}' in {filepath}")

            if key not in merged:
                merged[key] = copy.deepcopy(overrides)
                continue

            existing = merged[key]
            for field, value in overrides.items():
                if field in existing and existing[field] != value:
                    raise ValueError(
                        f"Conflict for user '{key}': field '{field}' has existing value "
                        f"'{existing[field]}', tried to set '{value}' in {filepath}"
                    )
            existing.update(copy.deepcopy(overrides))

    return merged


def _build_users(
    defs: OrderedDict[str, dict[str, Any]],
    primary_domain: str,
    start_id: int,
    become_pwd: str,
) -> OrderedDict[str, dict[str, Any]]:
    users: OrderedDict[str, dict[str, Any]] = OrderedDict()
    used_uids = set()

    for key, overrides in defs.items():
        if "uid" in overrides:
            uid = overrides["uid"]
            if uid in used_uids:
                raise ValueError(f"Duplicate uid {uid} for user '{key}'")
            used_uids.add(uid)

    next_uid = start_id

    def allocate_uid() -> int:
        nonlocal next_uid
        while next_uid in used_uids:
            next_uid += 1
        free_uid = next_uid
        used_uids.add(free_uid)
        next_uid += 1
        return free_uid

    for key, overrides in defs.items():
        username = overrides.get("username", key)
        firstname = overrides.get("firstname", f"{username}")
        lastname = overrides.get("lastname", f"{primary_domain}")
        email = overrides.get("email", f"{username}@{primary_domain}")
        description = overrides.get(
            "description", f"Created by Infinito.Nexus Ansible for {primary_domain}"
        )
        roles = overrides.get("roles", [])
        password = overrides.get("password", become_pwd)
        reserved = overrides.get("reserved", False)
        tokens = overrides.get("tokens", {})
        authorized_keys = overrides.get("authorized_keys", [])

        uid = overrides["uid"] if "uid" in overrides else allocate_uid()
        gid = overrides.get("gid", uid)

        users[key] = {
            "username": username,
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "password": password,
            "uid": uid,
            "gid": gid,
            "roles": roles,
            "tokens": tokens,
            "authorized_keys": authorized_keys,
            "reserved": reserved,
            "description": description,
        }

    seen_usernames: set[str] = set()
    seen_emails: set[str] = set()
    for key, entry in users.items():
        username = entry["username"]
        email = entry["email"]
        if username in seen_usernames:
            raise ValueError(f"Duplicate username '{username}' in merged users")
        if email in seen_emails:
            raise ValueError(f"Duplicate email '{email}' in merged users")
        seen_usernames.add(username)
        seen_emails.add(email)

    return users


def _load_store_users(file_tokens: Optional[str | os.PathLike[str]]) -> dict[str, Any]:
    if not file_tokens:
        return {}

    path = Path(file_tokens)
    if not path.exists():
        return {}

    data = _load_yaml_cached(path, default_if_missing={})
    users = data.get("users", {}) if isinstance(data, dict) else {}
    return users if isinstance(users, dict) else {}


def _resolve_tokens_file(variables: Optional[Mapping[str, Any]]) -> Path:
    candidates: list[Path] = []

    def _add_candidate(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            candidates.append(Path(text))

    variables = variables or {}
    _add_candidate(variables.get("FILE_TOKENS"))

    dir_secrets = variables.get("DIR_SECRETS")
    if dir_secrets:
        _add_candidate(Path(str(dir_secrets)) / "tokens.yml")

    dir_var_lib = variables.get("DIR_VAR_LIB")
    if dir_var_lib:
        _add_candidate(Path(str(dir_var_lib)) / "secrets" / "tokens.yml")

    _add_candidate(os.environ.get("FILE_TOKENS"))

    env_dir_secrets = os.environ.get("DIR_SECRETS")
    if env_dir_secrets:
        _add_candidate(Path(env_dir_secrets) / "tokens.yml")

    env_dir_var_lib = os.environ.get("DIR_VAR_LIB")
    if env_dir_var_lib:
        _add_candidate(Path(env_dir_var_lib) / "secrets" / "tokens.yml")

    # Read at call time so tests that patch
    # `utils.cache.base.DEFAULT_TOKENS_FILE` take effect on the very
    # next call rather than being shadowed by an import-time binding.
    candidates.append(_base.DEFAULT_TOKENS_FILE)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    return candidates[0]


def _hydrate_users_tokens(
    users: Optional[Mapping[str, Any]],
    store_users: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    def _as_stripped(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip()

    def _is_effectively_empty(value: Any) -> bool:
        stripped = _as_stripped(value)
        return stripped is None or stripped == ""

    out: dict[str, Any] = copy.deepcopy(dict(users or {}))
    if not store_users:
        return out

    for user_key, user_data in store_users.items():
        if not isinstance(user_data, Mapping):
            continue
        store_tokens = user_data.get("tokens", {})
        if not isinstance(store_tokens, Mapping):
            continue

        out_user = copy.deepcopy(dict(out.get(user_key, {}) or {}))
        out_tokens = copy.deepcopy(dict(out_user.get("tokens", {}) or {}))

        for app_id, store_token in store_tokens.items():
            token = _as_stripped(store_token)
            if token is None or token == "":
                continue
            if _is_effectively_empty(out_tokens.get(app_id)):
                out_tokens[app_id] = token

        out_user["tokens"] = out_tokens
        out[user_key] = out_user

    return out


def _materialize_builtin_user_aliases(
    users: Optional[Mapping[str, Any]],
    variables: Optional[Mapping[str, Any]],
    templar: Any = None,
) -> dict[str, Any]:
    # Lazy import: pulls `ansible.errors.AnsibleError` transitively, see the
    # base module note on why this stays out of the import block.
    from utils.templating import _templar_render_best_effort

    def _normalize_domain_candidate(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if ("{{" in text or "{%" in text) and variables:
            text = str(
                _templar_render_best_effort(templar, text, dict(variables))
            ).strip()
        if "://" in text:
            parsed = urlparse(text)
            text = parsed.hostname or text
        text = text.split("/", 1)[0].split(":", 1)[0].strip()
        return text

    def _to_primary_domain(value: Any) -> str:
        text = _normalize_domain_candidate(value)
        if not text:
            return ""
        labels = [label for label in text.split(".") if label]
        if len(labels) >= 2:
            return ".".join(labels[-2:])
        return text

    out: dict[str, Any] = copy.deepcopy(dict(users or {}))
    variables = variables or {}

    primary_domain = ""
    for candidate_key, extractor in (
        ("DOMAIN_PRIMARY", _normalize_domain_candidate),
        ("SYSTEM_EMAIL_DOMAIN", _normalize_domain_candidate),
        ("KEYCLOAK_DOMAIN", _to_primary_domain),
        ("domain", _to_primary_domain),
    ):
        primary_domain = extractor(variables.get(candidate_key))
        if primary_domain:
            break
    if not primary_domain:
        return out

    labels = [label for label in primary_domain.split(".") if label]
    alias_values = {
        "sld": labels[0] if labels else primary_domain,
        "tld": (labels[1] if len(labels) > 1 else (primary_domain + "_tld ")),
    }

    for alias_key, alias_value in alias_values.items():
        raw_user = out.get(alias_key)
        if not isinstance(raw_user, Mapping):
            continue

        raw_username = str(raw_user.get("username", ""))
        if "DOMAIN_PRIMARY.split" not in raw_username:
            continue

        updated_user = copy.deepcopy(dict(raw_user))
        updated_user["username"] = alias_value
        out[alias_key] = updated_user

    return out


def get_user_defaults(
    *, roles_dir: Optional[str | os.PathLike[str]] = None
) -> dict[str, Any]:
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _USERS_DEFAULTS_CACHE.get(key)
    if cached is None:
        definitions = _load_user_defs(resolved_roles_dir)
        for reserved_username in _compute_reserved_usernames(resolved_roles_dir):
            if reserved_username not in definitions:
                definitions[reserved_username] = {"reserved": True}
        built = _build_users(
            definitions,
            primary_domain="{{ DOMAIN_PRIMARY }}",
            start_id=1001,
            become_pwd="{{ 42 | strong_password }}",
        )
        cached = {key: built[key] for key in sorted(built)}
        _USERS_DEFAULTS_CACHE[key] = cached
    return copy.deepcopy(cached)


def get_merged_users(
    *,
    variables: Optional[dict[str, Any]] = None,
    roles_dir: Optional[str | os.PathLike[str]] = None,
    templar: Any = None,
) -> dict[str, Any]:
    source_variables = variables
    variables = dict(variables or {})
    if not variables.get("DOMAIN_PRIMARY") and variables.get("SYSTEM_EMAIL_DOMAIN"):
        variables["DOMAIN_PRIMARY"] = variables["SYSTEM_EMAIL_DOMAIN"]

    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    tokens_file = _resolve_tokens_file(variables)
    cache_key = (
        _cache_key(resolved_roles_dir),
        _stable_variables_signature(source_variables),
        _tokens_file_signature(tokens_file),
    )
    cached = _MERGED_USERS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    defaults = get_user_defaults(roles_dir=roles_dir)
    overrides = _resolve_override_mapping(variables, "users", templar=templar)

    merged = _merge_users(defaults, overrides)
    hydrated = _hydrate_users_tokens(
        merged,
        _load_store_users(tokens_file),
    )

    if getattr(_RENDER_GUARD, "users", False):
        # Re-entry via cross-lookup: skip the heavy materialize+render pass.
        return hydrated

    _RENDER_GUARD.users = True
    try:
        materialized = _materialize_builtin_user_aliases(
            hydrated,
            variables,
            templar=templar,
        )
        rendered = _render_with_templar(
            materialized,
            templar=templar,
            variables=variables,
            raw_users=materialized,
        )
    finally:
        _RENDER_GUARD.users = False

    _MERGED_USERS_CACHE[cache_key] = rendered
    return rendered


def _reset() -> None:
    _USERS_DEFAULTS_CACHE.clear()
    _MERGED_USERS_CACHE.clear()
