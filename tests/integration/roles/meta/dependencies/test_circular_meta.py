import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN


def load_yaml_file(file_path):
    """Load a YAML file via the cached helper."""
    return load_yaml_any(file_path, default_if_missing={}) or {}


def get_meta_info(role_path):
    """Extract dependencies from the meta/main.yml of a role."""
    meta_file = str(Path(role_path) / ROLE_FILE_META_MAIN)
    if not Path(meta_file).is_file():
        return []
    meta_data = load_yaml_file(meta_file)
    return meta_data.get("dependencies", [])


def resolve_dependencies(roles_dir):
    """Resolve all role dependencies and detect circular dependencies."""
    visited = set()  # Tracks roles that have been processed

    def visit(role_path, stack):
        role_name = Path(role_path).name

        if role_name in stack:
            raise ValueError(
                f"Circular dependency detected: {' -> '.join(stack)} -> {role_name}"
            )

        if role_name in visited:
            return []

        visited.add(role_name)
        stack.append(role_name)

        dependencies = get_meta_info(role_path)
        for dep in dependencies:
            dep_path = str(Path(roles_dir) / dep)
            visit(dep_path, stack)

        stack.pop()

        return None

    for role_name in os.listdir(roles_dir):
        role_path = str(Path(roles_dir) / role_name)
        if Path(role_path).is_dir():
            try:
                visit(role_path, [])
            except ValueError as e:
                raise ValueError(
                    f"Error processing role '{role_name}' at path '{role_path}': {e!s}"
                ) from e


class TestRoleDependencies(unittest.TestCase):
    def test_no_circular_dependencies(self):
        roles_dir = "roles"

        try:
            resolve_dependencies(roles_dir)
        except ValueError as e:
            self.fail(f"Circular dependency detected: {e}")

        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
