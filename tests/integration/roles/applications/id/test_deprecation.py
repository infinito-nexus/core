import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")


class TestApplicationIdDeprecation(unittest.TestCase):
    def test_application_id_matches_role_name(self):
        """
        Deprecation: application_id in vars/main.yml must match the role name.
        This test fails if any role violates this rule, listing all violations.
        """
        errors = []

        for role in os.listdir(ROLES_DIR):
            role_path = str(Path(ROLES_DIR) / role)
            vars_main_yml = str(Path(role_path) / ROLE_FILE_VARS_MAIN)
            if not Path(vars_main_yml).is_file():
                continue
            try:
                data = load_yaml_any(vars_main_yml)
            except Exception as e:
                errors.append(f"Could not parse {vars_main_yml}: {e}")
                continue
            if not isinstance(data, dict):
                continue
            app_id = data.get("application_id")
            if app_id is not None and app_id != role:
                errors.append(
                    f"[DEPRECATION] application_id '{app_id}' in {vars_main_yml} "
                    f"does not match its role directory '{role}'."
                )

        if errors:
            self.fail(
                "application_id mismatch found in one or more roles:\n\n"
                + "\n".join(errors)
                + "\n\nPlease update 'application_id' to match the role name for future compatibility."
            )


if __name__ == "__main__":
    unittest.main()
