from pathlib import Path
import os
import unittest

from utils.cache.files import iter_project_files


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


class TestTestFileNaming(unittest.TestCase):
    """
    Test-linter that enforces all Python files in the tests/
    directory to start with the 'test_' prefix.

    This guarantees consistent test naming and reliable
    test discovery.

    Files under ``tests/utils/`` are exempt because they hold shared
    test infrastructure (cached filesystem helpers, fixtures) rather
    than tests.
    """

    def test_all_python_files_use_test_prefix(self):
        root = repo_root()
        tests_root = root / "tests"
        tests_prefix = str(tests_root) + os.sep
        utils_prefix = str(tests_root / "utils") + os.sep

        invalid_files = []

        for path_str in iter_project_files(extensions=(".py",)):
            if not path_str.startswith(tests_prefix):
                continue
            path = Path(path_str)
            # Explicitly allow package initializers
            if path.name == "__init__.py":
                continue
            # Exempt shared test infrastructure under tests/utils/
            if path_str.startswith(utils_prefix):
                continue
            if not path.name.startswith("test_"):
                invalid_files.append(path.relative_to(tests_root))

        if invalid_files:
            self.fail(
                "The following Python files do not start with 'test_':\n"
                + "\n".join(f"- {p}" for p in invalid_files)
            )


if __name__ == "__main__":
    unittest.main()
