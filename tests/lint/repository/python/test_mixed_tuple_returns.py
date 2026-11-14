from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import python_modules

_RULE = "mixed-tuple-returns"
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _returns(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Return]:
    """Return the return statements of a function, not of the functions it nests.

    Args:
        function: the function.
    """
    found: list[ast.Return] = []
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            found.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return found


def _tuple_sizes(value: ast.expr | None) -> set[int]:
    """Return the lengths of the tuple literals an expression can evaluate to.

    Args:
        value: the returned expression.
    """
    if isinstance(value, ast.Tuple):
        return {len(value.elts)}
    if isinstance(value, ast.IfExp):
        return _tuple_sizes(value.body) | _tuple_sizes(value.orelse)
    return set()


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return the unannotated functions of one module that return tuples of several sizes.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    lines = content.splitlines()
    found: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, _FUNCTIONS) or function.returns is not None:
            continue
        sizes: set[int] = set()
        for statement in _returns(function):
            sizes |= _tuple_sizes(statement.value)
        if len(sizes) < 2:
            continue
        if is_suppressed_at(lines, function.lineno, _RULE, mode="same-or-above"):
            continue
        listed = ", ".join(str(size) for size in sorted(sizes))
        found.append(f"{rel_path}:{function.lineno}: {function.name} ({listed})")
    return found


class TestMixedTupleReturns(unittest.TestCase):
    def test_no_function_returns_tuples_of_several_sizes(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} function(s) without a return annotation return "
            f"tuple literals of different sizes:\n{report}\n\n"
            "Return one shape, or annotate a sequence whose length varies "
            "(`-> tuple[str, ...]`). An empty `return ()` beside real tuples "
            f"that must stay unannotated says why with `# nocheck: {_RULE} "
            "<reason>`.",
        )


class TestMixedTupleDetection(unittest.TestCase):
    def _run(self, source: str) -> list[str]:
        return _offenders("m.py", ast.parse(source), source)

    def test_a_nocheck_suppresses_it(self) -> None:
        source = (
            f"def f(x):  # nocheck: {_RULE} reason\n"
            "    if x:\n        return ()\n    return (1, 2)\n"
        )

        self.assertEqual([], self._run(source))

    def test_two_sizes_are_reported(self) -> None:
        source = (
            "def f(x):\n    if x:\n        return (1, 2)\n    return (1, 2, 3, 4)\n"
        )

        self.assertEqual(["m.py:1: f (2, 4)"], self._run(source))

    def test_a_conditional_expression_is_read_on_both_sides(self) -> None:
        source = "def f(c):\n    return (a, b, *c) if c else (b,)\n"

        self.assertEqual(["m.py:1: f (1, 3)"], self._run(source))

    def test_an_annotated_function_is_accepted(self) -> None:
        source = "def f(c) -> tuple[str, ...]:\n    return (a, b) if c else (b,)\n"

        self.assertEqual([], self._run(source))

    def test_one_size_is_accepted(self) -> None:
        source = "def f(x):\n    if x:\n        return (1, 2)\n    return (3, 4)\n"

        self.assertEqual([], self._run(source))

    def test_a_nested_function_is_judged_on_its_own(self) -> None:
        source = "def f():\n    def g():\n        return (1,)\n    return (1, 2)\n"

        self.assertEqual([], self._run(source))


if __name__ == "__main__":
    unittest.main()
