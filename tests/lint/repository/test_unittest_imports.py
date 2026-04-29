import os
import unittest

from utils.cache.files import iter_project_files_with_content


class TestUnittestImports(unittest.TestCase):
    TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def test_all_test_files_import_unittest(self):
        missing = []

        tests_prefix = self.TEST_ROOT + os.sep
        for filepath, content in iter_project_files_with_content(extensions=(".py",)):
            if not filepath.startswith(tests_prefix):
                continue
            filename = os.path.basename(filepath)
            # only consider test files named like "test_*.py"
            if not filename.startswith("test_"):
                continue

            # check for either import form
            if (
                "import unittest" not in content
                and "from unittest import" not in content
            ):
                rel_path = os.path.relpath(filepath, os.getcwd())
                missing.append(rel_path)

        if missing:
            self.fail(
                "The following test files do not import unittest:\n"
                + "\n".join(f"- {path}" for path in missing)
            )


if __name__ == "__main__":
    unittest.main()
