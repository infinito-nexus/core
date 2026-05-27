import unittest

import yaml

from plugins.filter.invokable_paths import get_invokable_paths
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


class TestApplicationIdConsistency(unittest.TestCase):
    def test_application_id_matches_docker_prefix(self):
        failed_roles = []
        prefixes = get_invokable_paths(suffix="-")

        for role_path in ROLES_DIR.iterdir():
            if not role_path.is_dir():
                continue

            role_name = role_path.name
            # check if the role name starts with one of our prefixes
            matching = [p for p in prefixes if role_name.startswith(p)]
            if not matching:
                continue

            prefix = matching[0]
            # expected_id is just the remainder after the prefix
            expected_id = role_name[len(prefix) :]

            vars_file = role_path / ROLE_FILE_VARS_MAIN
            if not vars_file.exists():
                failed_roles.append((role_name, "vars/main.yml missing"))
                continue

            try:
                vars_data = load_yaml_any(str(vars_file)) or {}
            except yaml.YAMLError as e:
                failed_roles.append((role_name, f"YAML error: {e}"))
                continue

            actual_id = vars_data.get("application_id")
            if actual_id not in [expected_id, role_name]:
                failed_roles.append(
                    (
                        role_name,
                        f"application_id is '{actual_id}', expected '{expected_id}'",
                    )
                )

        if failed_roles:
            msg = "\n".join(f"{r}: {reason}" for r, reason in failed_roles)
            self.fail(
                f"The following roles have mismatching or missing application_id:\n{msg}"
            )


if __name__ == "__main__":
    unittest.main()
