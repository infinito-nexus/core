import unittest
from pathlib import Path

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN

from . import PROJECT_ROOT


class TestRoleDependencies(unittest.TestCase):
    def test_dependencies_exist(self):
        roles_dir = Path(str(PROJECT_ROOT)) / "roles"
        roles_prefix = str(roles_dir) + "/"

        # Find all meta/main.yml files under roles/*/meta/main.yml
        meta_files = sorted(
            p
            for p in iter_project_files(extensions=(".yml",))
            if p.startswith(roles_prefix) and p.endswith(f"/{ROLE_FILE_META_MAIN}")
        )
        self.assertTrue(
            meta_files,
            f"No meta/main.yml files found under {roles_dir}",
        )

        for meta_file in meta_files:
            role_dir = str(Path(str(Path(meta_file).parent)).parent)
            role_name = Path(role_dir).name
            with self.subTest(role=role_name):
                # Load the YAML metadata via the cached helper.
                meta = load_yaml_any(meta_file, default_if_missing={}) or {}

                # Extract dependencies list
                dependencies = meta.get("dependencies", [])
                self.assertIsInstance(
                    dependencies,
                    list,
                    f"'dependencies' for role '{role_name}' is not a list",
                )

                for dep in dependencies:
                    # Dependencies can be strings or dicts with a 'role' key
                    if isinstance(dep, str):
                        dep_name = dep
                    elif isinstance(dep, dict) and "role" in dep:
                        dep_name = dep["role"]
                    else:
                        self.fail(
                            f"Invalid dependency format {dep!r} in role '{role_name}'"
                        )

                    dep_path = roles_dir / dep_name
                    # Assert that the dependency role directory exists
                    self.assertTrue(
                        dep_path.is_dir(),
                        f"Role '{role_name}' declares dependency '{dep_name}' but '{dep_path}' does not exist",
                    )


if __name__ == "__main__":
    unittest.main()
