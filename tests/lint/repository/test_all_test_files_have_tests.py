#!/usr/bin/env python3
import ast
import os
import unittest
from pathlib import Path
from typing import List

from utils.cache.files import read_text


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


class TestTestFilesContainUnittestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = repo_root()
        self.tests_dir = self.repo_root / "tests"
        self.assertTrue(
            self.tests_dir.is_dir(),
            f"'tests' directory not found at: {self.tests_dir}",
        )

    def _iter_test_files(self) -> List[str]:
        out: List[str] = []
        for root, _dirs, files in os.walk(self.tests_dir):
            for fn in files:
                if fn.startswith("test_") and fn.endswith(".py"):
                    out.append(os.path.join(root, fn))
        return sorted(out)

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

        # Collect local aliases for TestCase (e.g. "from unittest import TestCase as TC")
        testcase_aliases = {"TestCase"}
        unittest_aliases = {"unittest"}

        for node in tree.body:
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name == "unittest":
                        unittest_aliases.add(n.asname or "unittest")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "unittest":
                    for n in node.names:
                        if n.name == "TestCase":
                            testcase_aliases.add(n.asname or "TestCase")

        def is_testcase_base(base: ast.expr) -> bool:
            # TestCase
            if isinstance(base, ast.Name) and base.id in testcase_aliases:
                return True
            # unittest.TestCase or alias.TestCase
            if isinstance(base, ast.Attribute) and base.attr == "TestCase":
                if (
                    isinstance(base.value, ast.Name)
                    and base.value.id in unittest_aliases
                ):
                    return True
            return False

        # 1) module-level test_* function (uncommon but valid for discovery in some setups)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                return True
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                return True

        # 2) unittest.TestCase subclasses with at least one test_* method
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
            # Avoid self-check loops if you name this file test_*.py (it should not be)
            rel = os.path.relpath(path, str(self.repo_root))
            if not self._file_contains_runnable_unittest_test(path):
                offenders.append(rel)

        self.assertFalse(
            offenders,
            "These test_*.py files do not define any unittest-runnable tests:\n"
            + "\n".join(f"- {p}" for p in offenders),
        )


if __name__ == "__main__":
    unittest.main()
