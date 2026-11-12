"""Static-inventory group lookups (YAML + INI)."""

from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import load_yaml_any, load_yaml_tagged


def inventory_has_group(inventory_path: str, group_name: str) -> bool:
    if Path(inventory_path).suffix in (".yml", ".yaml"):
        data = load_yaml_any(inventory_path, default_if_missing={})
        return _find_yaml_key(data, group_name)
    return _find_ini_section(inventory_path, group_name)


def inventory_groups(inventory_path: str) -> set[str]:
    """Return every group a static inventory file declares.

    Ansible tags such as ``!unsafe`` and ``!vault`` load as opaque values.

    Args:
        inventory_path: YAML (``.yml``/``.yaml``) or INI inventory file.
    """
    if Path(inventory_path).suffix in (".yml", ".yaml"):
        return _yaml_groups(load_yaml_tagged(inventory_path))
    return _ini_groups(inventory_path)


def _yaml_groups(node) -> set[str]:
    groups: set[str] = set()
    if not isinstance(node, dict):
        return groups
    for name, body in node.items():
        groups.add(str(name))
        if isinstance(body, dict):
            groups |= _yaml_groups(body.get("children"))
    return groups


def _ini_groups(inventory_path: str) -> set[str]:
    groups: set[str] = set()
    in_children = False
    with Path(inventory_path).open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                name, _, kind = line[1:-1].strip().partition(":")
                groups.add(name)
                in_children = kind == "children"
                continue
            if in_children:
                groups.add(line.split()[0])
    return groups


def _find_yaml_key(node, key: str) -> bool:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, (dict, list)):
                return True
            if _find_yaml_key(v, key):
                return True
    elif isinstance(node, list):
        for item in node:
            if _find_yaml_key(item, key):
                return True
    return False


def _find_ini_section(inventory_path: str, group_name: str) -> bool:
    with Path(inventory_path).open(encoding="utf-8") as f:
        current_section: str | None = None
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                if current_section == group_name:
                    return True
                continue
            if current_section:
                for part in line.replace(",", " ").split():
                    if part.strip() == group_name:
                        return True
    return False
