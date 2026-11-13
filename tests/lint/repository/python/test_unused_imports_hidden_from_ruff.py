from __future__ import annotations

import ast
import re
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import (
    ACCEPTABLE_UNUSED,
    declared_all,
    module_level,
    python_modules,
    read_names,
)

_RULE = "unused-import"
_NOQA_F401 = re.compile(r"#\s*noqa:[^#]*\bF401\b", re.IGNORECASE)


def _bound(alias: ast.alias) -> str:
    """Return the name an import alias binds in the importing module.

    Args:
        alias: one entry of an import statement.
    """
    if alias.asname:
        return alias.asname
    return alias.name.split(".")[0]


def _hidden_from_ruff(alias: ast.alias, lines: list[str]) -> bool:
    """Whether ruff's F401 lets the import pass although nothing reads it.

    Args:
        alias: one entry of an import statement.
        lines: the module's lines.
    """
    redundant = alias.asname is not None and alias.asname == alias.name
    return redundant or bool(_NOQA_F401.search(lines[alias.lineno - 1]))


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return the unused imports of one module that ruff is told to accept.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    if rel_path.endswith("__init__.py"):
        return []
    statements = module_level(tree.body)
    exported = declared_all(tree, statements)
    if exported is None:
        return []
    used = read_names(tree, content)
    lines = content.splitlines()
    found: list[str] = []
    for node in statements:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        for alias in node.names:
            name = _bound(alias)
            if alias.name == "*" or name in used or name in exported:
                continue
            if ACCEPTABLE_UNUSED.fullmatch(name):
                continue
            if is_suppressed_at(lines, alias.lineno, _RULE, mode="same-or-above"):
                continue
            if _hidden_from_ruff(alias, lines):
                found.append(f"{rel_path}:{node.lineno}: {name}")
    return found


class TestUnusedImportsHiddenFromRuff(unittest.TestCase):
    def test_no_module_keeps_an_import_nothing_reads(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} import(s) bind a name the module never reads; "
            "a redundant `as` alias or `# noqa: F401` keeps ruff quiet, but the "
            f"import is still unused:\n{report}\n\n"
            "Import the name where it is used, from the module that defines "
            "it, and drop it here. For an import kept for its side effect, "
            f"say so with `# nocheck: {_RULE} <reason>`.",
        )


class TestHiddenImportDetection(unittest.TestCase):
    def _run(self, source: str, rel: str = "m.py") -> list[str]:
        return _offenders(rel, ast.parse(source), source)

    def test_a_redundant_alias_nothing_reads_is_reported(self) -> None:
        self.assertEqual(["m.py:1: mask"], self._run("from s import mask as mask\n"))

    def test_a_noqa_import_nothing_reads_is_reported(self) -> None:
        self.assertEqual(
            ["m.py:1: utils"], self._run("import utils.handler.vault  # noqa: F401\n")
        )

    def test_a_plain_unused_import_is_left_to_ruff(self) -> None:
        self.assertEqual([], self._run("from s import mask\n"))

    def test_a_redundant_alias_the_module_reads_is_accepted(self) -> None:
        self.assertEqual([], self._run("from s import mask as mask\nmask('x')\n"))

    def test_a_name_in_all_is_accepted(self) -> None:
        source = 'from s import mask as mask\n\n__all__ = ["mask"]\n'

        self.assertEqual([], self._run(source))

    def test_a_package_init_is_skipped(self) -> None:
        self.assertEqual([], self._run("from s import mask as mask\n", "p/__init__.py"))

    def test_a_function_level_import_is_skipped(self) -> None:
        self.assertEqual([], self._run("def f():\n    import x  # noqa: F401\n"))

    def test_an_import_under_a_guard_still_counts(self) -> None:
        source = (
            "import contextlib\n"
            "with contextlib.suppress(ImportError):\n"
            "    import readline  # noqa: F401\n"
        )

        self.assertEqual(["m.py:3: readline"], self._run(source))

    def test_a_nocheck_suppresses_it(self) -> None:
        source = f"# nocheck: {_RULE} registers a loader\nimport x.y  # noqa: F401\n"

        self.assertEqual([], self._run(source))


if __name__ == "__main__":
    unittest.main()
