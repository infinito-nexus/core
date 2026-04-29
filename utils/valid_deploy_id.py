"""
Utility for validating deployment application IDs against defined roles and inventory.
"""

from __future__ import annotations

import os
from pathlib import Path
from utils.cache.yaml import load_yaml_any

from plugins.filter.get_all_application_ids import get_all_application_ids


class ValidDeployId:
    def __init__(self) -> None:
        """
        Always resolve roles/ from the repository root, independent of CWD.
        """
        repo_root = Path(__file__).resolve().parents[1]
        roles_dir = repo_root / "roles"

        if not roles_dir.is_dir():
            raise RuntimeError(
                f"roles directory not found at expected location: {roles_dir}"
            )

        self.roles_dir = roles_dir
        self.valid_ids = set(get_all_application_ids(str(roles_dir)))

    def validate(
        self, inventory_path: str, ids: list[str]
    ) -> dict[str, dict[str, bool]]:
        """
        Validate a list of application IDs against both role definitions and inventory.

        Returns:
          {
            "app1": {"in_roles": False, "in_inventory": True},
            "app2": {"in_roles": True, "in_inventory": False},
          }
        """
        invalid: dict[str, dict[str, bool]] = {}

        for app_id in ids:
            in_roles = app_id in self.valid_ids
            in_inventory = self._exists_in_inventory(inventory_path, app_id)

            if not (in_roles and in_inventory):
                invalid[app_id] = {
                    "in_roles": in_roles,
                    "in_inventory": in_inventory,
                }

        return invalid

    def _exists_in_inventory(self, inventory_path: str, app_id: str) -> bool:
        _, ext = os.path.splitext(inventory_path)
        if ext in (".yml", ".yaml"):
            return self._search_yaml_keys(inventory_path, app_id)
        return self._search_ini_sections(inventory_path, app_id)

    def _search_ini_sections(self, inventory_path: str, app_id: str) -> bool:
        with open(inventory_path, "r", encoding="utf-8") as f:
            current_section = None
            for raw in f:
                line = raw.strip()
                if not line or line.startswith(("#", ";")):
                    continue

                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1].strip()
                    if current_section == app_id:
                        return True
                    continue

                if current_section:
                    for part in line.replace(",", " ").split():
                        if part.strip() == app_id:
                            return True

        return False

    def _search_yaml_keys(self, inventory_path: str, app_id: str) -> bool:
        data = load_yaml_any(inventory_path, default_if_missing={})
        return self._find_key(data, app_id)

    def _find_key(self, node, key: str) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key and isinstance(v, (dict, list)):
                    return True
                if self._find_key(v, key):
                    return True
        elif isinstance(node, list):
            for item in node:
                if self._find_key(item, key):
                    return True
        return False
