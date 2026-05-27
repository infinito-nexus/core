import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN


class TestRunAfterReferences(unittest.TestCase):
    """
    Integration test: ensure that every name listed under
    galaxy_info.run_after in each role's meta/main.yml
    corresponds to an existing role directory.
    """

    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.roles_dir = str(PROJECT_ROOT / "roles")
        # collect all role names (folder names) in roles/
        cls.existing_roles = {
            name
            for name in os.listdir(cls.roles_dir)
            if Path(str(Path(cls.roles_dir) / name)).is_dir()
        }

    def test_run_after_points_to_existing_roles(self):
        errors = []
        for role in sorted(self.existing_roles):
            meta_path = str(Path(self.roles_dir) / role / ROLE_FILE_META_MAIN)
            if not Path(meta_path).is_file():
                # skip roles without a meta/main.yml
                continue

            data = load_yaml_any(meta_path, default_if_missing={}) or {}

            run_after = data.get("galaxy_info", {}).get("run_after", [])
            errors.extend(
                f"Role '{role}' declares run_after: '{dep}', but '{dep}' is not a directory under roles/"
                for dep in run_after
                if dep not in self.existing_roles
            )

        if errors:
            self.fail(
                "Some run_after references are invalid:\n  " + "\n  ".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
