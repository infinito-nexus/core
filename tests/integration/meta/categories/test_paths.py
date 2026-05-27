import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT


class TestCategoryPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        file_path = str(PROJECT_ROOT / "roles" / "categories.yml")
        data = load_yaml_any(file_path)
        cls.roles_def = data["roles"]

        roles_dir = PROJECT_ROOT / "roles"
        cls.existing_dirs = [p.name for p in roles_dir.iterdir()]

    def test_all_category_paths_exist(self):
        expected = set()

        for top_key, attrs in self.roles_def.items():
            # Top-level category
            expected.add(top_key)

            # Nested subcategories (keys other than metadata)
            for sub_key in attrs:
                # Skip metadata keys
                if sub_key in ("title", "description", "icon", "children", "invokable"):
                    continue
                expected.add(f"{top_key}-{sub_key}")

        missing = []
        missing.extend(
            name
            for name in expected
            if not any(name in dirname for dirname in self.existing_dirs)
        )

        if missing:
            self.fail(f"Missing role directories for: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    unittest.main()
