"""Entity-name SPOT.

A role's entity name keys its instance directory, its compose project and
its container name. It is derived from the role name by stripping the
longest matching category path, unless the role declares a literal
``entity_name`` in ``vars/main.yml``, which wins.

Two roles under different categories whose names share a suffix
(``svc-ai-libretranslate`` and ``web-svc-libretranslate``) otherwise
collapse onto one entity and overwrite each other's rendered stack. The
declaration is the escape hatch that keeps both role names intact;
``tests/lint/ansible/roles/meta/test_service_key_collision.py`` enforces
that no two compose-rendering roles end up on the same entity either way.

``PROJECT_ROOT`` is read inside the functions, never pre-joined at import
time, for the reason :mod:`utils.roles.categories` states: tests patch the
root and build fixtures in temporary trees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.categories import (
    categories_file,
    flatten_categories,
    load_categories_tree,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

if TYPE_CHECKING:
    from pathlib import Path


def declared_entity_name(role_name: str, root: Path | None = None) -> str:
    """The literal ``entity_name`` a role declares, or ``""``.

    Args:
        role_name: role directory name / application id.
        root: tree to resolve against; the repository root when omitted.

    Returns:
        The declared name, or ``""`` when the role declares none, derives
        it through a Jinja expression, or has no ``vars/main.yml``.
    """
    base = PROJECT_ROOT if root is None else root
    data = load_yaml_any(
        str(base / "roles" / role_name / ROLE_FILE_VARS_MAIN),
        default_if_missing={},
    )
    declared = data.get("entity_name") if isinstance(data, dict) else None
    if not isinstance(declared, str):
        return ""
    declared = declared.strip()
    return "" if "{{" in declared else declared


def entity_name(role_name):
    """
    Get the entity name from a role name by removing the
    longest matching category path from categories.yml.
    """
    declared = declared_entity_name(role_name)
    if declared:
        return declared

    categories_tree = load_categories_tree(str(categories_file()))
    all_category_paths = flatten_categories(categories_tree)

    role_name_lc = role_name.lower()
    all_category_paths = [cat.lower() for cat in all_category_paths]
    empty_match = False
    for cat in sorted(all_category_paths, key=len, reverse=True):
        if role_name_lc.startswith(cat + "-"):
            return role_name[len(cat) + 1 :]
        if role_name_lc == cat:
            empty_match = True
    return "" if empty_match else role_name
