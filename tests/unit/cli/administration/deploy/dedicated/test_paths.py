from __future__ import annotations

import unittest
from pathlib import Path

from cli.administration.deploy.dedicated import paths


class TestPaths(unittest.TestCase):
    def test_project_root_resolves_to_repo(self):
        self.assertTrue(Path(paths.PROJECT_ROOT).is_dir())
        self.assertTrue((Path(paths.PROJECT_ROOT) / "pyproject.toml").is_file())

    def test_derived_paths_are_consistent(self):
        self.assertEqual(paths.CLI_ROOT, str(Path(paths.PROJECT_ROOT) / "cli"))
        self.assertEqual(
            paths.PLAYBOOK_PATH, str(Path(paths.PROJECT_ROOT) / "playbook.yml")
        )
        self.assertEqual(
            paths.MODES_FILE,
            str(Path(paths.PROJECT_ROOT) / "group_vars" / "all" / "01_modes.yml"),
        )
        self.assertEqual(
            paths.INVENTORY_VALIDATOR_PATH,
            str(
                Path(paths.PROJECT_ROOT)
                / "cli"
                / "administration"
                / "inventory"
                / "validate"
                / "__main__.py"
            ),
        )


if __name__ == "__main__":
    unittest.main()
