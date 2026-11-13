from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from utils.cache import base as _base
from utils.cache.yaml import load_yaml as _load_yaml_cached

STORE_FACT = "sys_token_store_users"

_DIGESTS: dict[str, str] = {}


def snapshot(variables: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Return the token store the play read from the stack host.

    Args:
        variables: the play's variable scope.

    Returns:
        The ``sys_token_store_users`` fact, or None outside a play that loaded
        ``sys-token-store``.
    """
    value = (variables or {}).get(STORE_FACT)
    return value if isinstance(value, Mapping) else None


def _tagged(value: Any) -> list:
    return [True, str(value)] if isinstance(value, str) else [False, repr(value)]


def tokens_digest(store_users: Mapping[str, Any]) -> str:
    """Digest exactly the part of a store that `_hydrate_users_tokens` reads.

    Args:
        store_users: the store's ``users`` mapping.

    Returns:
        The SHA-256 of every user entry with a tokens mapping, in store order,
        and its non-empty stripped tokens, memoised per store content.
    """
    memo_key = hashlib.md5(
        repr(list(store_users.items())).encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    digest = _DIGESTS.get(memo_key)
    if digest is not None:
        return digest
    entries: list = []
    for user_key, user_data in store_users.items():
        if not isinstance(user_data, Mapping):
            continue
        tokens = user_data.get("tokens", {})
        if not isinstance(tokens, Mapping):
            continue
        kept = []
        for app_id, token in tokens.items():
            text = "" if token is None else str(token).strip()
            if text:
                kept.append([_tagged(app_id), text])
        entries.append([_tagged(user_key), kept])
    digest = hashlib.sha256(json.dumps(entries).encode("utf-8")).hexdigest()
    _DIGESTS[memo_key] = digest
    return digest


def load_store_users(file_tokens: str | os.PathLike[str] | None) -> dict[str, Any]:
    if not file_tokens:
        return {}

    path = Path(file_tokens)
    if not path.exists():
        return {}

    data = _load_yaml_cached(path, default_if_missing={})
    users = data.get("users", {}) if isinstance(data, dict) else {}
    return users if isinstance(users, dict) else {}


def store_signature(variables: Mapping[str, Any] | None, tokens_file: Path) -> tuple:
    """Return the cache-key part of the store the users are hydrated from.

    Args:
        variables: the play's variable scope.
        tokens_file: the controller's tokens file, used when no snapshot exists.

    Returns:
        ``(STORE_FACT, digest)``, equal for the tokens file and the
        ``sys_token_store_users`` fact when both hold the same tokens.
    """
    current = snapshot(variables)
    store = current if current is not None else load_store_users(tokens_file)
    return (STORE_FACT, tokens_digest(store))


def resolve_tokens_file(variables: Mapping[str, Any] | None) -> Path:
    candidates: list[Path] = []

    def _add_candidate(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            candidates.append(Path(text))

    variables = variables or {}
    _add_candidate(variables.get("FILE_TOKENS"))

    tokens_name = _base.DEFAULT_TOKENS_FILE.name
    secrets_name = _base.DEFAULT_TOKENS_FILE.parent.name

    dir_secrets = variables.get("DIR_SECRETS")
    if dir_secrets:
        _add_candidate(Path(str(dir_secrets)) / tokens_name)

    dir_var_lib = variables.get("DIR_VAR_LIB")
    if dir_var_lib:
        _add_candidate(Path(str(dir_var_lib)) / secrets_name / tokens_name)

    _add_candidate(os.environ.get("FILE_TOKENS"))

    env_dir_secrets = os.environ.get("DIR_SECRETS")
    if env_dir_secrets:
        _add_candidate(Path(env_dir_secrets) / tokens_name)

    env_dir_var_lib = os.environ.get("DIR_VAR_LIB")
    if env_dir_var_lib:
        _add_candidate(Path(env_dir_var_lib) / secrets_name / tokens_name)

    candidates.append(_base.DEFAULT_TOKENS_FILE)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    return candidates[0]


def _reset() -> None:
    _DIGESTS.clear()
