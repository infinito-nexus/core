#!/usr/bin/env python3
import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN

from . import PROJECT_ROOT


class TestRunAfterRoles(unittest.TestCase):
    def setUp(self):
        self.roles_dir = PROJECT_ROOT / "roles"
        self.valid_role_names = {p.name for p in self.roles_dir.iterdir() if p.is_dir()}

    def test_run_after_roles_are_valid(self):
        invalid_refs = []

        for role in self.valid_role_names:
            meta_path = self.roles_dir / role / ROLE_FILE_META_MAIN
            if not meta_path.exists():
                continue

            try:
                data = load_yaml_any(meta_path) or {}
            except Exception as e:
                self.fail(f"Failed to parse {meta_path}: {e}")
                continue

            run_after = data.get("galaxy_info", {}).get("run_after", [])
            invalid_refs.extend(
                (role, ref) for ref in run_after if ref not in self.valid_role_names
            )

        if invalid_refs:
            msg = "\n".join(
                f"{role}: invalid run_after → {ref}" for role, ref in invalid_refs
            )
            self.fail(f"Found invalid run_after references:\n{msg}")


if __name__ == "__main__":
    unittest.main()
