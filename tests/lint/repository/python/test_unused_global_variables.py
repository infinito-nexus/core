from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import (
    ACCEPTABLE_UNUSED,
    declared_all,
    module_level,
    python_modules,
    read_names,
)

_RULE = "unused-global"


def _visible(node: ast.expr) -> bool:
    """Whether a value is plain enough that an analyser sees it exported without ``__all__``.

    Args:
        node: the assigned value.
    """
    if isinstance(node, (ast.Constant, ast.Name, ast.Attribute)):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_visible(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(_visible(key) for key in node.keys if key is not None) and all(
            _visible(value) for value in node.values
        )
    if isinstance(node, ast.BinOp):
        return _visible(node.left) and _visible(node.right)
    if isinstance(node, ast.UnaryOp):
        return _visible(node.operand)
    return False


def _bindings(statements: list[ast.stmt]) -> list[tuple[list[ast.Name], ast.expr]]:
    """Return each module-level assignment's target names and its value.

    Args:
        statements: the module-level statements.
    """
    found: list[tuple[list[ast.Name], ast.expr]] = []
    for node in statements:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.append(([target], node.value))
                elif isinstance(target, (ast.Tuple, ast.List)):
                    names = [e for e in target.elts if isinstance(e, ast.Name)]
                    found.append((names, node.value))
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            found.append(([node.target], node.value))
    return found


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return the module-level variables of one module that it neither reads nor exports.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    statements = module_level(tree.body)
    exported = declared_all(tree, statements)
    package = rel_path.endswith("__init__.py")
    if exported is None or not (exported or package):
        return []
    used = read_names(tree, content)
    lines = content.splitlines()
    found: list[str] = []
    for names, value in _bindings(statements):
        unread = [
            name
            for name in names
            if name.id not in used
            and name.id not in exported
            and not ACCEPTABLE_UNUSED.fullmatch(name.id)
            and not is_suppressed_at(lines, name.lineno, _RULE, mode="same-or-above")
        ]
        if not names or len(unread) != len(names):
            continue
        if not exported and _visible(value):
            continue
        found.extend(f"{rel_path}:{name.lineno}: {name.id}" for name in unread)
    return found


class TestUnusedGlobalVariables(unittest.TestCase):
    def test_no_module_level_variable_goes_unread(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} module-level variable(s) are never read by their "
            f"module and not declared as its exports:\n{report}\n\n"
            "Delete a variable nothing reads. A module with `__all__`, and a "
            "package `__init__.py` handing a computed value to its modules, "
            "list it in `__all__`, or have its readers import it from where "
            "it is defined. A name other modules import but `__all__` must not "
            f"publish says why with `# nocheck: {_RULE} <reason>`.",
        )


class TestUnreadGlobalDetection(unittest.TestCase):
    def _run(self, source: str, rel: str = "m.py") -> list[str]:
        return _offenders(rel, ast.parse(source), source)

    def test_a_name_missing_from_all_is_reported(self) -> None:
        source = '__all__ = ["run"]\nTIMEOUT = LIMIT\ndef run():\n    pass\n'

        self.assertEqual(["m.py:2: TIMEOUT"], self._run(source))

    def test_a_nocheck_suppresses_it(self) -> None:
        source = f'__all__ = ["run"]\nTIMEOUT = LIMIT  # nocheck: {_RULE} reason\n'

        self.assertEqual([], self._run(source))

    def test_a_computed_value_in_a_package_init_is_reported(self) -> None:
        source = "ROOT = Path(__file__).parents[2]\n"

        self.assertEqual(["p/__init__.py:1: ROOT"], self._run(source, "p/__init__.py"))

    def test_a_package_init_declaring_all_is_accepted(self) -> None:
        source = 'ROOT = Path(__file__).parents[2]\n__all__ = ["ROOT"]\n'

        self.assertEqual([], self._run(source, "p/__init__.py"))

    def test_a_plain_value_in_a_package_init_is_accepted(self) -> None:
        self.assertEqual([], self._run("HANDLERS = [a, b]\n", "p/__init__.py"))

    def test_a_module_without_all_is_skipped(self) -> None:
        self.assertEqual([], self._run("GLOB = f'roles/{P}*'\n"))

    def test_a_variable_the_module_reads_is_accepted(self) -> None:
        source = "ROOT = Path('.')\ndef f():\n    return ROOT\n"

        self.assertEqual([], self._run(source, "p/__init__.py"))

    def test_a_tuple_with_one_read_element_is_accepted(self) -> None:
        source = '__all__ = ["f"]\nA, B = g()\ndef f():\n    return A\n'

        self.assertEqual([], self._run(source))

    def test_an_underscore_name_is_accepted(self) -> None:
        self.assertEqual([], self._run("_ = setup()\n", "p/__init__.py"))


if __name__ == "__main__":
    unittest.main()
