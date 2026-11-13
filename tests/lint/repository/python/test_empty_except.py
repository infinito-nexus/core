from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import python_modules

_RULE = "empty-except"
_SIMPLE = (
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Delete,
    ast.Assert,
    ast.Import,
    ast.ImportFrom,
    ast.Pass,
)
_EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
_FOCUSSED = {
    "subscript": {"LookupError", "KeyError", "IndexError"},
    "attribute": {"AttributeError"},
    "name": {"NameError"},
    "encode": {"UnicodeEncodeError"},
    "decode": {"UnicodeDecodeError"},
}


def _caught(handler: ast.ExceptHandler) -> set[str]:
    """Return the exception names a handler catches.

    Args:
        handler: the except clause.
    """
    kinds = handler.type
    elements = kinds.elts if isinstance(kinds, ast.Tuple) else [kinds]
    return {
        element.id if isinstance(element, ast.Name) else getattr(element, "attr", "")
        for element in elements
        if element is not None
    }


def _shape(statement: ast.stmt) -> str:
    """Return what a lone statement does, for the handlers that catch only that.

    Args:
        statement: the only statement of the try body.
    """
    targets = getattr(statement, "targets", None) or []
    value = getattr(statement, "value", None)
    probe = targets[0] if isinstance(statement, ast.Delete) and targets else value
    if isinstance(probe, ast.Subscript):
        return "subscript"
    if isinstance(probe, ast.Attribute):
        return "attribute"
    if isinstance(statement, ast.Expr) and isinstance(value, ast.Name):
        return "name"
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name) and func.id in ("getattr", "setattr", "delattr"):
            return "attribute"
        if isinstance(func, ast.Attribute) and func.attr in ("encode", "decode"):
            return func.attr
    return ""


def _left_to_ruff(node: ast.Try) -> bool:
    """Whether the try statement has the one shape ruff's SIM105 already reports.

    Args:
        node: the try statement.
    """
    return (
        len(node.handlers) == 1
        and not node.orelse
        and not node.finalbody
        and len(node.body) == 1
        and isinstance(node.body[0], _SIMPLE)
    )


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return the except clauses of one module that do nothing but pass.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    lines = content.splitlines()
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Try, ast.TryStar)) or node.orelse:
            continue
        if isinstance(node.body[-1], _EXITS) or _left_to_ruff(node):
            continue
        lone = _shape(node.body[0]) if len(node.body) == 1 else ""
        for handler in node.handlers:
            if not all(isinstance(s, ast.Pass) for s in handler.body):
                continue
            caught = _caught(handler)
            if "StopIteration" in caught:
                continue
            if lone and caught and caught <= _FOCUSSED[lone]:
                continue
            if is_suppressed_at(lines, handler.lineno, _RULE, mode="same-or-above"):
                continue
            found.append(f"{rel_path}:{handler.lineno}")
    return found


class TestEmptyExcept(unittest.TestCase):
    def test_no_except_clause_only_passes(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} except clause(s) do nothing but pass:\n{report}\n\n"
            "Wrap the statements in `contextlib.suppress(<error>)` so the "
            "ignored error is named where the block starts, or handle it. "
            f"Where neither fits, say why with `# nocheck: {_RULE} <reason>`.",
        )


class TestEmptyExceptDetection(unittest.TestCase):
    def _run(self, source: str) -> list[str]:
        return _offenders("m.py", ast.parse(source), source)

    def test_a_nocheck_suppresses_it(self) -> None:
        source = (
            "try:\n    a()\n    b()\n"
            f"except OSError:  # nocheck: {_RULE} reason\n    pass\n"
        )

        self.assertEqual([], self._run(source))

    def test_a_two_statement_body_is_reported(self) -> None:
        source = "try:\n    a()\n    b()\nexcept OSError:\n    pass\n"

        self.assertEqual(["m.py:4"], self._run(source))

    def test_a_compound_body_is_reported(self) -> None:
        source = "try:\n    for x in y:\n        a(x)\nexcept ValueError:\n    pass\n"

        self.assertEqual(["m.py:4"], self._run(source))

    def test_the_single_statement_shape_is_left_to_ruff(self) -> None:
        self.assertEqual([], self._run("try:\n    a()\nexcept OSError:\n    pass\n"))

    def test_a_handler_that_acts_is_accepted(self) -> None:
        source = "try:\n    a()\n    b()\nexcept OSError:\n    c()\n"

        self.assertEqual([], self._run(source))

    def test_a_try_with_else_is_accepted(self) -> None:
        source = "try:\n    a()\n    b()\nexcept OSError:\n    pass\nelse:\n    c()\n"

        self.assertEqual([], self._run(source))

    def test_a_body_that_always_returns_is_accepted(self) -> None:
        source = "def f():\n    try:\n        a()\n        return b()\n    except OSError:\n        pass\n"

        self.assertEqual([], self._run(source))

    def test_stop_iteration_is_accepted(self) -> None:
        source = "try:\n    a()\n    b()\nexcept StopIteration:\n    pass\n"

        self.assertEqual([], self._run(source))


if __name__ == "__main__":
    unittest.main()
