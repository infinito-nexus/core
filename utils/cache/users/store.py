"""The token store the users are hydrated from: the play fact and its digest."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

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


def _reset() -> None:
    _DIGESTS.clear()
