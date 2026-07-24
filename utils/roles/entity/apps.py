"""Reverse entity -> application_id resolver.

`utils.roles.entity.name.get_entity_name` maps a role / application_id to
its compose entity name (the longest matching category prefix stripped).
The purge orchestrators need the inverse: given an entity name, which
application_ids belong to it? This helper walks the roles directory and
returns that mapping.

Used by `utils.cleanup.nginx_vhosts` so an entity-keyed purge can
enumerate the per-app domains whose nginx vhost files belong to the
stack being torn down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path


def _role_app_id(role_dir: Path) -> str:
    """Return the role's application_id (vars/main.yml.application_id),
    falling back to the directory name when the field is missing or the
    file does not exist. Mirrors `utils.roles.validation.invokable._role_to_app_id`.
    """
    vars_file = role_dir / ROLE_FILE_VARS_MAIN
    if not vars_file.is_file():
        return role_dir.name
    data = load_yaml_any(str(vars_file), default_if_missing={}) or {}
    if not isinstance(data, dict):
        return role_dir.name
    app_id = data.get("application_id")
    return str(app_id) if app_id else role_dir.name


def apps_for_entity(entity: str, *, roles_dir: Path) -> list[str]:
    """Return sorted, deduplicated application_ids whose role belongs to
    *entity* under `get_entity_name`.

    Returns an empty list when *entity* is blank, *roles_dir* is not a
    directory, or no role matches.
    """
    target = entity.strip()
    if not target or not roles_dir.is_dir():
        return []

    out: set[str] = set()
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        app_id = _role_app_id(role_dir)
        if not app_id:
            continue
        if get_entity_name(app_id) == target:
            out.add(app_id)
    return sorted(out)
