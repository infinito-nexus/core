"""
Utility for validating deployment application IDs against defined roles and inventory.
"""

from __future__ import annotations

from plugins.filter.get_all_application_ids import get_all_application_ids
from utils.inventory.groups import inventory_has_group

from . import PROJECT_ROOT


class ValidDeployId:
    def __init__(self) -> None:
        """
        Always resolve roles/ from the repository root, independent of CWD.
        """
        repo_root = PROJECT_ROOT
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
            in_inventory = inventory_has_group(inventory_path, app_id)

            if not (in_roles and in_inventory):
                invalid[app_id] = {
                    "in_roles": in_roles,
                    "in_inventory": in_inventory,
                }

        return invalid
