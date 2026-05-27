from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.applications.resolution.combined import repo_paths
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)


class TestCombinedRepoPaths(unittest.TestCase):
    def test_roles_dir_and_role_paths(self) -> None:
        root = Path("/tmp/fake-root")

        with patch.object(repo_paths, "PROJECT_ROOT", root):
            self.assertEqual(repo_paths.roles_dir(), root / "roles")
            self.assertEqual(
                repo_paths.role_dir("web-app-x"), root / "roles" / "web-app-x"
            )
            self.assertEqual(
                repo_paths.role_meta_path("web-app-x"),
                root / "roles" / "web-app-x" / ROLE_FILE_META_MAIN,
            )
            self.assertEqual(
                repo_paths.role_vars_path("web-app-x"),
                root / "roles" / "web-app-x" / ROLE_FILE_VARS_MAIN,
            )
            self.assertEqual(
                repo_paths.role_config_path("web-app-x"),
                root / "roles" / "web-app-x" / ROLE_FILE_META_SERVICES,
            )


if __name__ == "__main__":
    unittest.main()
