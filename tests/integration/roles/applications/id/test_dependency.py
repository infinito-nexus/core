import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT


class TestDependencyApplicationId(unittest.TestCase):
    def test_application_id_matches_folder_for_dependent_roles(self):
        """
        For any role A that depends on role B (listed under A/meta/main.yml → dependencies),
        if both A and B have vars/main.yml with application_id defined,
        then application_id must equal the role's folder name for both.
        """
        roles_dir = PROJECT_ROOT / "roles"

        violations = []

        # Helper to load application_id if present
        def load_app_id(role_path):
            vars_file = Path(role_path) / ROLE_FILE_VARS_MAIN
            if not vars_file.is_file():
                return None
            data = load_yaml_any(str(vars_file)) or {}
            return data.get("application_id")

        # Iterate all roles
        for role_path in roles_dir.iterdir():
            if not role_path.is_dir():
                continue

            role_name = role_path.name
            meta_file = role_path / ROLE_FILE_META_MAIN
            if not meta_file.is_file():
                continue

            meta = load_yaml_any(str(meta_file)) or {}

            deps = meta.get("dependencies", [])
            if not isinstance(deps, list):
                continue

            # collect just the role names this role depends on
            dep_names = []
            for item in deps:
                if isinstance(item, dict) and "role" in item:
                    dep_names.append(item["role"])
                elif isinstance(item, str):
                    dep_names.append(item)

            # load application_id for this role once
            app_id_role = load_app_id(role_path)
            for dep_name in dep_names:
                dep_path = roles_dir / dep_name
                if not dep_path.is_dir():
                    continue

                app_id_dep = load_app_id(dep_path)
                # only check if both app_ids are defined
                if app_id_role is None or app_id_dep is None:
                    continue

                # check role A
                if app_id_role != role_name:
                    violations.append(
                        f"{role_name}: application_id='{app_id_role}' ≠ folder name '{role_name}'"
                    )
                # check role B
                if app_id_dep != dep_name:
                    violations.append(
                        f"{dep_name}: application_id='{app_id_dep}' ≠ folder name '{dep_name}'"
                    )

        if violations:
            self.fail(
                "application_id mismatches between role folder names and vars/main.yml:\n"
                + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
