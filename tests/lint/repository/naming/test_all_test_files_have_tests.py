#!/usr/bin/env python3
import ast
import os
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT


class TestTestFilesContainUnittestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tests_dir = PROJECT_ROOT / "tests"
        self.assertTrue(
            self.tests_dir.is_dir(),
            f"'tests' directory not found at: {self.tests_dir}",
        )

    def _iter_test_files(self) -> list[str]:
        tests_prefix = str(self.tests_dir) + os.sep
        return sorted(
            p
            for p in iter_project_files(extensions=(".py",))
            if p.startswith(tests_prefix) and Path(p).name.startswith("test_")
        )

    def _file_contains_runnable_unittest_test(self, path: str) -> bool:
        """
        Return True if the file contains at least one unittest-runnable test:
        - a function named test_* at module level (rare), OR
        - a class inheriting from unittest.TestCase (directly or via alias) with at least one method test_*.
        """
        src = read_text(path)

        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            raise AssertionError(f"SyntaxError in {path}: {e}") from e

        testcase_aliases = {"TestCase"}
        unittest_aliases = {"unittest"}

        for node in tree.body:
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name == "unittest":
                        unittest_aliases.add(n.asname or "unittest")
            if isinstance(node, ast.ImportFrom) and node.module == "unittest":
                for n in node.names:
                    if n.name == "TestCase":
                        testcase_aliases.add(n.asname or "TestCase")

        def is_testcase_base(base: ast.expr) -> bool:
            if isinstance(base, ast.Name) and base.id in testcase_aliases:
                return True
            return bool(
                isinstance(base, ast.Attribute)
                and base.attr == "TestCase"
                and isinstance(base.value, ast.Name)
                and base.value.id in unittest_aliases
            )

        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                return True
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                return True

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(is_testcase_base(b) for b in node.bases):
                continue
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("test_"):
                    return True

        return False

    def test_all_test_py_files_contain_runnable_tests(self) -> None:
        test_files = self._iter_test_files()
        self.assertTrue(test_files, "No test_*.py files found under tests/")

        offenders = []
        for path in test_files:
            rel = os.path.relpath(path, str(PROJECT_ROOT))
            if not self._file_contains_runnable_unittest_test(path):
                offenders.append(rel)

        self.assertFalse(
            offenders,
            "These test_*.py files do not define any unittest-runnable tests:\n"
            + "\n".join(f"- {p}" for p in offenders),
        )


if __name__ == "__main__":
    unittest.main()
