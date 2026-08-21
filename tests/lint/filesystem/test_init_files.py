import unittest

from . import PROJECT_ROOT

NON_PYTHON = frozenset({"javascript", "php", "ruby"})


def _is_python_tree(relative_parts) -> bool:
    """Return whether a path under ``tests/`` holds Python tests.

    ``tests/<type>/<language>/`` splits the suites by language, so anything
    below a non-Python language root is discovered by that language's runner
    and must not carry a Python package marker.

    :param relative_parts: the directory's parts relative to ``tests/``
    :return: ``True`` when the directory is part of the Python test tree
    """
    return len(relative_parts) < 2 or relative_parts[1] not in NON_PYTHON


class TestInitFiles(unittest.TestCase):
    def test_all_test_dirs_have_init(self):
        """
        Ensure every Python subdirectory in the 'tests' folder (excluding '__pycache__') contains an '__init__.py' file.
        """
        tests_root = PROJECT_ROOT / "tests"

        for path in tests_root.rglob("*"):  # nocheck: project-walk
            if path.is_dir() and "__pycache__" not in path.parts:
                relative = path.relative_to(tests_root)
                if not _is_python_tree(relative.parts):
                    continue
                init_file = path / "__init__.py"
                with self.subTest(directory=str(relative)):
                    self.assertTrue(
                        init_file.exists(), f"Missing __init__.py in directory: {path}"
                    )


if __name__ == "__main__":
    unittest.main()
