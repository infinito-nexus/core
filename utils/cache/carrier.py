"""Play-scoped carriers of the rendered applications and users payloads.

Ansible forks a fresh worker process per task, so the in-process
`_MERGED_APPLICATIONS_CACHE` and `_MERGED_USERS_CACHE` start empty in every
worker. The constructor stage renders once and parks each payload plus its
cache key in the host facts named by `APPLICATIONS_RENDERED_FACT` and
`USERS_RENDERED_FACT`; every later worker inherits those facts at fork time
and `get_merged_applications` / `get_merged_users` serve them instead of
rendering. Ansible-free at import time like the rest of the package.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .base import (
    _cache_key,
    _resolve_roles_dir,
    _revalidate_tokens_file,
    _stable_variables_signature,
)

if TYPE_CHECKING:
    import os

APPLICATIONS_RENDERED_FACT = "_INFINITO_APPLICATIONS_RENDERED"
USERS_RENDERED_FACT = "_INFINITO_USERS_RENDERED"


def merged_applications_cache_key(
    variables: Mapping[str, Any] | None,
    *,
    roles_dir: str | os.PathLike[str] | None = None,
) -> tuple[str, tuple]:
    """Key under which one rendered applications payload stays valid.

    Args:
        variables: The play's variable scope. Only the subset that
            `_stable_variables_signature` reads influences the key; the token
            store keys the users carrier instead (`merged_users_cache_key`).
        roles_dir: Roles tree the payload is built from; defaults to the
            repository's `roles/`.

    Returns:
        ``(resolved roles dir, stable variables signature)``.
    """
    return (
        _cache_key(_resolve_roles_dir(roles_dir=roles_dir)),
        _stable_variables_signature(variables),
    )


def merged_users_cache_key(
    variables: Mapping[str, Any] | None,
    *,
    roles_dir: str | os.PathLike[str] | None = None,
) -> tuple[str, tuple]:
    """Key under which one rendered users payload stays valid.

    Args:
        variables: The play's variable scope. The applications key's inputs,
            the token store the users are hydrated from and
            ``inventory_hostname`` influence the key.
        roles_dir: Roles tree the payload is built from; defaults to the
            repository's `roles/`.

    Returns:
        ``(resolved roles dir, applications key signature extended by the
        token store signature and the host the payload was rendered for)``.
    """
    from .users import _resolve_tokens_file, _store_signature

    roles_key, signature = merged_applications_cache_key(variables, roles_dir=roles_dir)
    tokens = _store_signature(variables, _resolve_tokens_file(variables))
    host = (variables or {}).get("inventory_hostname")
    return (
        roles_key,
        (*signature, *(str(part) for part in tokens), str(host or "")),
    )


def revalidate_tokens_file(variables: Mapping[str, Any] | None) -> None:
    """Refresh an NFS client's attributes of the tokens file before a carrier is keyed.

    Args:
        variables: The play's variable scope the tokens file resolves from.
    """
    from .users import _resolve_tokens_file

    _revalidate_tokens_file(_resolve_tokens_file(variables))


def _carried(
    variables: Mapping[str, Any],
    fact: str,
    field: str,
    cache_key: tuple[str, tuple],
) -> dict[str, Any] | None:
    """Return the payload carried in *fact* when its key equals *cache_key*,
    else ``None``.

    Args:
        variables: The play's variable scope, read for the carrier fact.
        fact: The carrier fact's name.
        field: The carrier's payload field.
        cache_key: The key the caller would render under.
    """
    carrier = variables.get(fact)
    if not isinstance(carrier, Mapping):
        return None
    key = carrier.get("key")
    payload = carrier.get(field)
    if (
        not isinstance(payload, Mapping)
        or not isinstance(key, (list, tuple))
        or len(key) != 2
        or not isinstance(key[1], (list, tuple))
    ):
        return None
    if [str(key[0]), [str(part) for part in key[1]]] != [
        cache_key[0],
        list(cache_key[1]),
    ]:
        return None
    return payload


def _carried_applications(
    variables: Mapping[str, Any], cache_key: tuple[str, tuple]
) -> dict[str, Any] | None:
    """Return the payload carried in `APPLICATIONS_RENDERED_FACT` when its
    key equals *cache_key*, else ``None``.

    Args:
        variables: The play's variable scope, read for the carrier fact.
        cache_key: The key the caller would render under.
    """
    return _carried(variables, APPLICATIONS_RENDERED_FACT, "applications", cache_key)


def _carried_users(
    variables: Mapping[str, Any], cache_key: tuple[str, tuple]
) -> dict[str, Any] | None:
    """Return the payload carried in `USERS_RENDERED_FACT` when its key
    equals *cache_key*, else ``None``.

    Args:
        variables: The play's variable scope, read for the carrier fact.
        cache_key: The key the caller would render under.
    """
    return _carried(variables, USERS_RENDERED_FACT, "users", cache_key)
