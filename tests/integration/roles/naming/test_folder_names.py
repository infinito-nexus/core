#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


class TestRolesFolderNames(unittest.TestCase):
    def test_no_underscore_in_role_folder_names(self):
        """
        Integration test that verifies none of the folders under 'roles' contain an underscore in their name,
        ignoring the '__pycache__' folder.
        """
        from . import PROJECT_ROOT

        roles_dir = str(PROJECT_ROOT / "roles")

        # List all entries in the roles directory
        entries = []
        try:
            entries = os.listdir(roles_dir)
        except FileNotFoundError:
            self.fail(f"Roles directory not found at expected location: {roles_dir}")

        # Identify any role folders containing underscores, excluding '__pycache__'
        invalid = []
        for name in entries:
            # Skip the '__pycache__' directory
            if name == "__pycache__":
                continue
            path = str(Path(roles_dir) / name)
            if Path(path).is_dir() and "_" in name:
                invalid.append(name)

        # Fail the test if any invalid folder names are found
        if invalid:
            self.fail(
                f"Role folder names must not contain underscores: {', '.join(sorted(invalid))}"
            )


if __name__ == "__main__":
    unittest.main()
