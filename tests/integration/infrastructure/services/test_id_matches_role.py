#!/usr/bin/env python3
import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any


class TestSystemServiceIdMatchesRole(unittest.TestCase):
    def setUp(self):
        from . import PROJECT_ROOT

        self.repo_root = str(PROJECT_ROOT)
        self.roles_dir = str(PROJECT_ROOT / "roles")
        self.assertTrue(
            Path(self.roles_dir).is_dir(),
            f"'roles' directory not found at: {self.roles_dir}",
        )

    def _load_yaml(self, path: str):
        return load_yaml_any(path) or {}

    def test_system_service_id_equals_role_name(self):
        role_dirs = [
            d
            for d in os.listdir(self.roles_dir)
            if Path(str(Path(self.roles_dir) / d)).is_dir()
        ]

        self.assertGreater(
            len(role_dirs), 0, f"No role directories found in {self.roles_dir}"
        )

        for role in sorted(role_dirs):
            with self.subTest(role=role):
                vars_dir = Path(self.roles_dir) / role / "vars"
                if not vars_dir.is_dir():
                    continue

                candidates = [
                    str(vars_dir / name)
                    for name in ("main.yml", "main.yaml")
                    if (vars_dir / name).is_file()
                ]
                if not candidates:
                    continue

                vars_file = min(
                    candidates, key=lambda p: (not p.endswith("main.yml"), p)
                )
                data = self._load_yaml(vars_file)

                if "system_service_id" not in (data or {}):
                    continue

                value = str(data.get("system_service_id")).strip()
                allowed = {role, role + "@", "{{ application_id }}"}

                self.assertIn(
                    value,
                    allowed,
                    (
                        f"[{role}] system_service_id mismatch in {vars_file}.\n"
                        f"  Allowed: {sorted(allowed)}\n"
                        f"  Actual:  {value}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
