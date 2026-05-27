"""Role-type detection.

Role-type detection consumes the ``marker: True`` entries declared in
:data:`utils.roles.mapping.ROLE_FILES` so the schema and the predicate
share one source of truth: adding a new type marker on the SPOT side
makes the predicate recognise the new type without further code edits.

A role MAY belong to more than one type. ``svc-opt-ssd-hdd`` is the
canonical example: it declares both ``application_id`` and
``system_service_id`` and is therefore an application AND a system
service. :func:`get_role_types` returns the full set so callers that
care about scope (e.g. lint tests asserting "this file is allowed for
applications") can use simple set membership.

Algorithm
---------

For every marker entry declared anywhere in
:data:`utils.roles.mapping.ROLE_FILES` the predicate reads the role's
file at the entry's dotted path. Each marker that resolves to a
non-empty string adds the surrounding type to the result.

Roles without any marker fall back to:

* :data:`utils.roles.mapping.ROLE_TYPE_USER` for the bare ``user``
  role and every ``user-<…>`` sibling (name-based);
* :data:`utils.roles.mapping.ROLE_TYPE_TOOLING` otherwise.

Conformance
-----------

A marker value MUST be a non-empty string. If the marker key is
present but the value is of the wrong YAML type, empty, or whitespace-
only, the role's typing is broken: :func:`get_role_types` raises
:class:`RoleTypeError` so the misconfiguration surfaces at the first
call instead of silently degrading to a different type.

Caching
-------

Reads route through :func:`utils.cache.yaml.load_yaml_any` (already
memoised per-path). :func:`get_role_types` caches its return per
role-directory string so repeated calls during a single test sweep
stay free.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILES,
    ROLE_TYPE_TOOLING,
    ROLE_TYPE_USER,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class RoleTypeError(ValueError):
    """Raised when a role's typing markers do not conform to the schema."""


def _all_markers() -> Iterator[tuple[str, str, str]]:
    """Yield ``(role_type, file_rel_path, dotted_path)`` for every
    ``marker: True`` entry in :data:`utils.roles.mapping.ROLE_FILES`.
    """
    for file_rel_path, file_entry in ROLE_FILES.items():
        types = file_entry.get("types") or []
        for type_entry in types:
            if not isinstance(type_entry, dict):
                continue
            role_type = type_entry.get("type")
            if not isinstance(role_type, str):
                continue
            for sub_entry in type_entry.get("entries") or []:
                if not isinstance(sub_entry, dict):
                    continue
                if not sub_entry.get("marker"):
                    continue
                path = sub_entry.get("path")
                if isinstance(path, str) and path:
                    yield role_type, file_rel_path, path


def _resolve_dotted(data: object, dotted: str) -> object:
    """Walk *dotted* (``a.b.c``) into *data*. Return ``None`` when any
    segment is missing or *data* turns into a non-mapping mid-walk.
    """
    cursor: object = data
    for segment in dotted.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(segment)
    return cursor


def _check_marker_value(
    role_dir: Path,
    file_rel_path: str,
    dotted: str,
    value: object,
) -> str | None:
    """Return the trimmed marker string when present, ``None`` when the
    path is absent. Raise :class:`RoleTypeError` for an empty / non-
    string value, since the schema does not allow it.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise RoleTypeError(
            f"{role_dir.name}: {file_rel_path}.{dotted} MUST be a string "
            f"when set, got {type(value).__name__}."
        )
    trimmed = value.strip()
    if not trimmed:
        raise RoleTypeError(
            f"{role_dir.name}: {file_rel_path}.{dotted} is set but empty; "
            "remove the key or assign a non-empty value."
        )
    return trimmed


def _is_user_role(role_name: str) -> bool:
    return role_name == "user" or role_name.startswith("user-")


def _read_role_file(role_dir: Path, file_rel_path: str) -> object | None:
    abs_path = role_dir / file_rel_path
    if not abs_path.is_file():
        return None
    return load_yaml_any(str(abs_path), default_if_missing={})


@cache
def _get_role_types_cached(role_dir_str: str) -> frozenset[str]:
    role_dir = Path(role_dir_str)

    # Memoise per-file reads across the marker walk so a file that
    # carries multiple markers (e.g. ``vars/main.yml``) is parsed once.
    file_data_cache: dict[str, object] = {}

    found: set[str] = set()
    for role_type, file_rel_path, dotted in _all_markers():
        if file_rel_path not in file_data_cache:
            file_data_cache[file_rel_path] = _read_role_file(role_dir, file_rel_path)
        data = file_data_cache[file_rel_path]
        if data is None:
            continue
        if not isinstance(data, dict):
            raise RoleTypeError(
                f"{role_dir.name}: {file_rel_path} MUST be a YAML "
                f"mapping at the file root, got {type(data).__name__}."
            )
        value = _check_marker_value(
            role_dir, file_rel_path, dotted, _resolve_dotted(data, dotted)
        )
        if value is not None:
            found.add(role_type)

    if found:
        return frozenset(found)

    if _is_user_role(role_dir.name):
        return frozenset({ROLE_TYPE_USER})
    return frozenset({ROLE_TYPE_TOOLING})


def get_role_types(role_dir: Path) -> frozenset[str]:
    """Return the set of role types declared by *role_dir*'s markers.

    A role MAY belong to several types simultaneously (for example an
    application that also ships a systemd unit). The returned frozenset
    contains every type whose marker matches; the user / tooling
    fallbacks fire only when no marker resolves.

    Cached: repeated calls for the same *role_dir* reuse the first
    parse. Pass an absolute path so the cache key is stable across
    callers that resolve relative paths differently.
    """
    return _get_role_types_cached(str(role_dir))


def reset_cache_for_tests() -> None:
    """Drop the per-process role-type cache. Tests that mutate
    ``vars/main.yml`` (or another marker-bearing file) mid-run MUST
    call this between mutations.
    """
    _get_role_types_cached.cache_clear()
