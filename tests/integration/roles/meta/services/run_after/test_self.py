import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN


class TestSelfDependency(unittest.TestCase):
    """
    Integration test: ensure no role lists itself in its own 'run_after'
    in meta/main.yml.
    """

    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.roles_dir = str(PROJECT_ROOT / "roles")

    def test_no_self_in_run_after(self):
        for entry in os.listdir(self.roles_dir):
            role_path = str(Path(self.roles_dir) / entry)
            meta_file = str(Path(role_path) / ROLE_FILE_META_MAIN)
            if not Path(role_path).is_dir() or not Path(meta_file).is_file():
                continue

            data = load_yaml_any(meta_file, default_if_missing={}) or {}

            run_after = data.get("galaxy_info", {}).get("run_after", [])
            if entry in run_after:
                self.fail(
                    f"Role '{entry}' has a self-dependency in its run_after list "
                    f"in {meta_file}"
                )


if __name__ == "__main__":
    unittest.main()
