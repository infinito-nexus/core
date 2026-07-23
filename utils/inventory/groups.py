"""Static-inventory group-existence checks (YAML + INI)."""

from __future__ import annotations

from pathlib import Path

from utils.cache.yaml import load_yaml_any


def inventory_has_group(inventory_path: str, group_name: str) -> bool:
    if Path(inventory_path).suffix in (".yml", ".yaml"):
        data = load_yaml_any(inventory_path, default_if_missing={})
        return _find_yaml_key(data, group_name)
    return _find_ini_section(inventory_path, group_name)


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
