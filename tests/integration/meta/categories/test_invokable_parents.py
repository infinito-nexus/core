import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.categories import categories_file


class TestCategoriesInvokableExclusion(unittest.TestCase):
    def test_no_child_invokable_if_any_parent_is_invokable(self):
        """
        Verify that if any ancestor in the hierarchy is invokable,
        none of its descendants may be invokable.
        """
        yaml_path = str(categories_file())

        data = load_yaml_any(yaml_path)

        violations = []

        def recurse(node: dict, path: list[str], ancestor_invokable: bool):
            for key, value in node.items():
                if not isinstance(value, dict):
                    continue

                is_invokable = value.get("invokable", False)
                current_path = [*path, key]

                if ancestor_invokable and is_invokable:
                    ancestor_name = ".".join(path) if path else "<root>"
                    violations.append(
                        f"{'.'.join(current_path)} is invokable, "
                        f"but its ancestor ({ancestor_name}) is also invokable."
                    )

                new_ancestor_flag = ancestor_invokable or is_invokable

                for subkey, subval in value.items():
                    if isinstance(subval, dict):
                        recurse({subkey: subval}, current_path, new_ancestor_flag)

        recurse(data.get("roles", {}), [], False)

        if violations:
            self.fail(
                "Found invokable descendants under invokable parents:\n"
                + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
