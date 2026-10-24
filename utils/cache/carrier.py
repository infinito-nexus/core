"""Play-scoped carrier of the rendered applications payload.

Ansible forks a fresh worker process per task, so the in-process
`_MERGED_APPLICATIONS_CACHE` starts empty in every worker. The constructor
stage renders once and parks the payload plus its cache key in the host fact
named by `APPLICATIONS_RENDERED_FACT`; every later worker inherits that fact
at fork time and `get_merged_applications` serves it instead of rendering.
Ansible-free at import time like the rest of the package.
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


def merged_applications_cache_key(
    variables: Mapping[str, Any] | None,
    *,
    roles_dir: str | os.PathLike[str] | None = None,
) -> tuple[str, tuple]:
    """Key under which one rendered applications payload stays valid.

    Args:
        variables: The play's variable scope. Only the subset that
            `_stable_variables_signature` reads, and the token store the users
            are hydrated from, influence the key.
        roles_dir: Roles tree the payload is built from; defaults to the
            repository's `roles/`.

    Returns:
        ``(resolved roles dir, stable variables signature extended by the
        token store signature)``.
    """
    from .users import _resolve_tokens_file, _store_signature

    tokens = _store_signature(variables, _resolve_tokens_file(variables))
    return (
        _cache_key(_resolve_roles_dir(roles_dir=roles_dir)),
        (*_stable_variables_signature(variables), *(str(part) for part in tokens)),
    )


def revalidate_tokens_file(variables: Mapping[str, Any] | None) -> None:
    """Refresh an NFS client's attributes of the tokens file before a carrier is keyed.

    Args:
        variables: The play's variable scope the tokens file resolves from.
    """
    from .users import _resolve_tokens_file

    _revalidate_tokens_file(_resolve_tokens_file(variables))


def _carried_applications(
    variables: Mapping[str, Any], cache_key: tuple[str, tuple]
) -> dict[str, Any] | None:
    """Return the payload carried in `APPLICATIONS_RENDERED_FACT` when its
    key equals *cache_key*, else ``None``.

    Args:
        variables: The play's variable scope, read for the carrier fact.
        cache_key: The key the caller would render under.
    """
    carrier = variables.get(APPLICATIONS_RENDERED_FACT)
    if not isinstance(carrier, Mapping):
        return None
    key = carrier.get("key")
    payload = carrier.get("applications")
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
