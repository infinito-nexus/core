from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import python_modules

_RULE = "import-and-import-from"


def _from_module(node: ast.ImportFrom, rel_path: str) -> str:
    """Return the absolute name of the module an ``import from`` reads.

    Args:
        node: the statement.
        rel_path: path of the importing file relative to the project root.
    """
    if not node.level:
        return node.module or ""
    package = rel_path.removesuffix(".py").split("/")[:-1]
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, *([node.module] if node.module else [])])


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return every ``import`` of a module the same file also imports from.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    read_from = {
        _from_module(node, rel_path)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    lines = content.splitlines()
    return [
        f"{rel_path}:{node.lineno}: {alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name in read_from
        and not is_suppressed_at(lines, node.lineno, _RULE, mode="same-or-above")
    ]


class TestImportAndImportFrom(unittest.TestCase):
    def test_no_module_is_imported_in_both_forms(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} module(s) are imported with both `import m` and "
            "`from m import x` in the same file, so one name reaches the module "
            f"by two routes:\n{report}\n\n"
            "Keep one form: qualify the names through the module, or import "
            "the submodule itself (`import unittest.mock`). Where both forms "
            f"are needed, say why with `# nocheck: {_RULE} <reason>`.",
        )


class TestBothFormsDetection(unittest.TestCase):
    def _run(self, source: str, rel: str = "m.py") -> list[str]:
        return _offenders(rel, ast.parse(source), source)

    def test_import_and_import_from_is_reported(self) -> None:
        self.assertEqual(
            ["m.py:1: unittest"],
            self._run("import unittest\nfrom unittest import mock\n"),
        )

    def test_an_imported_submodule_is_accepted(self) -> None:
        self.assertEqual([], self._run("import unittest\nimport unittest.mock\n"))

    def test_importing_from_a_submodule_is_accepted(self) -> None:
        self.assertEqual(
            [], self._run("import unittest\nfrom unittest.mock import patch\n")
        )

    def test_a_function_level_import_from_still_counts(self) -> None:
        source = "import os\n\ndef f():\n    from os import path\n"

        self.assertEqual(["m.py:1: os"], self._run(source))

    def test_a_relative_import_resolves_against_the_package(self) -> None:
        source = "import pkg.sub\nfrom . import sub\nfrom .sub import x\n"

        self.assertEqual(["pkg/m.py:1: pkg.sub"], self._run(source, "pkg/m.py"))

    def test_a_nocheck_suppresses_it(self) -> None:
        source = (
            f"import typing  # nocheck: {_RULE} reason\n"
            "from typing import TYPE_CHECKING\n"
        )

        self.assertEqual([], self._run(source))


if __name__ == "__main__":
    unittest.main()
