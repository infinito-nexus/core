# tests/unit/cli/meta/applications/resolution/combined/test_repo_paths.py
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.resolution.combined import repo_paths


class TestCombinedRepoPaths(unittest.TestCase):
    def test_roles_dir_and_role_paths(self) -> None:
        root = Path("/tmp/fake-root")

        with patch.object(repo_paths, "repo_root_from_here", return_value=root):
            self.assertEqual(repo_paths.roles_dir(), root / "roles")
            self.assertEqual(
                repo_paths.role_dir("web-app-x"), root / "roles" / "web-app-x"
            )
            self.assertEqual(
                repo_paths.role_meta_path("web-app-x"),
                root / "roles" / "web-app-x" / "meta" / "main.yml",
            )
            self.assertEqual(
                repo_paths.role_vars_path("web-app-x"),
                root / "roles" / "web-app-x" / "vars" / "main.yml",
            )
            self.assertEqual(
                repo_paths.role_config_path("web-app-x"),
                root / "roles" / "web-app-x" / "meta" / "services.yml",
            )


if __name__ == "__main__":
    unittest.main()
