import os
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT


class TestTestFileNaming(unittest.TestCase):
    """
    Test-linter that enforces all Python files in the tests/
    directory to start with the 'test_' prefix or with a leading
    underscore (``_*.py``).

    The leading-underscore form is reserved for shared test
    infrastructure that lives next to the tests it backs (for
    example ``_scan.py`` / ``_validate.py`` in
    ``tests/integration/lookups/config/``). The underscore prefix
    keeps unittest discovery from picking these modules up as test
    cases while still allowing them to import the surrounding
    package's ``test_*.py`` files via relative imports.

    This guarantees consistent test naming and reliable
    test discovery.

    Files under ``tests/utils/`` are exempt because they hold shared
    test infrastructure (cached filesystem helpers, fixtures) rather
    than tests.
    """

    def test_all_python_files_use_test_prefix(self):
        tests_root = PROJECT_ROOT / "tests"
        tests_prefix = str(tests_root) + os.sep
        utils_prefix = str(tests_root / "utils") + os.sep

        invalid_files = []

        for path_str in iter_project_files(extensions=(".py",)):
            if not path_str.startswith(tests_prefix):
                continue
            path = Path(path_str)
            # Allow package initializers and shared-helper modules
            # (``_scan.py``, ``_validate.py``, etc.) — anything whose
            # filename starts with an underscore.
            if path.name.startswith("_"):
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
