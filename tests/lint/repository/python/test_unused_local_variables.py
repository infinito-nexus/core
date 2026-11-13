from __future__ import annotations

import ast
import re
import unittest

from utils.annotations.suppress import is_suppressed_at

from . import ACCEPTABLE_UNUSED, python_modules

_RULE = "unused-local"
_RUFF_DUMMY = re.compile(r"_+|_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _own_statements(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Return the nodes of a function body outside its nested functions and classes.

    Args:
        function: the function.
    """
    found: list[ast.AST] = []
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        found.append(node)
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return found


def _targets(node: ast.AST) -> list[list[ast.Name]]:
    """Return the name groups one statement binds, a tuple target as one group.

    Args:
        node: a node of the function body.
    """
    if isinstance(node, ast.Assign):
        raw = node.targets
    elif (isinstance(node, ast.AnnAssign) and node.value is not None) or isinstance(
        node, ast.NamedExpr
    ):
        raw = [node.target]
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        raw = [node.optional_vars]
    else:
        return []
    groups: list[list[ast.Name]] = []
    for target in raw:
        if isinstance(target, ast.Name):
            groups.append([target])
        elif isinstance(target, (ast.Tuple, ast.List)):
            groups.append([e for e in target.elts if isinstance(e, ast.Name)])
    return groups


def _offenders(rel_path: str, tree: ast.Module, content: str) -> list[str]:
    """Return the dummy-named locals of one module that nothing reads.

    Args:
        rel_path: path relative to the project root.
        tree: the parsed module.
        content: the module's text.
    """
    lines = content.splitlines()
    found: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, _FUNCTIONS):
            continue
        read = {
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store)
        }
        shared = {
            name
            for node in ast.walk(function)
            if isinstance(node, (ast.Global, ast.Nonlocal))
            for name in node.names
        }
        for node in _own_statements(function):
            for group in _targets(node):
                unread = [n for n in group if n.id not in read and n.id not in shared]
                if not group or len(unread) != len(group):
                    continue
                found.extend(
                    f"{rel_path}:{name.lineno}: {name.id}"
                    for name in unread
                    if _RUFF_DUMMY.fullmatch(name.id)
                    and not ACCEPTABLE_UNUSED.fullmatch(name.id)
                    and not is_suppressed_at(
                        lines, name.lineno, _RULE, mode="same-or-above"
                    )
                )
    return found


class TestUnusedLocalVariables(unittest.TestCase):
    def test_no_underscore_local_goes_unread(self) -> None:
        offenders: list[str] = []
        for rel, content, tree in python_modules():
            offenders.extend(_offenders(rel, tree, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} local variable(s) carry a leading underscore, "
            "which keeps ruff quiet, but nothing reads them:\n"
            f"{report}\n\n"
            "Bind only what is used: index or slice the value, or use a bare "
            "`_` for a position the code has to skip. A binding that has to "
            f"live, such as a keepalive, says why with `# nocheck: {_RULE} "
            "<reason>`.",
        )


class TestUnusedLocalDetection(unittest.TestCase):
    def _run(self, source: str) -> list[str]:
        return _offenders("m.py", ast.parse(source), source)

    def test_a_nocheck_suppresses_it(self) -> None:
        source = f"def f():\n    _keep = g()  # nocheck: {_RULE} reason\n"

        self.assertEqual([], self._run(source))

    def test_an_unread_underscore_name_is_reported(self) -> None:
        source = "def f():\n    _name, self.email = g()\n"

        self.assertEqual(["m.py:2: _name"], self._run(source))

    def test_a_bare_underscore_is_accepted(self) -> None:
        self.assertEqual([], self._run("def f():\n    _, b = g()\n    return b\n"))

    def test_a_tuple_with_a_read_element_is_accepted(self) -> None:
        source = "def f():\n    _name, email = g()\n    return email\n"

        self.assertEqual([], self._run(source))

    def test_a_plain_unread_name_is_left_to_ruff(self) -> None:
        self.assertEqual([], self._run("def f():\n    name = g()\n"))

    def test_a_name_read_in_a_closure_is_accepted(self) -> None:
        source = "def f():\n    _cache = {}\n    def g():\n        return _cache\n    return g\n"

        self.assertEqual([], self._run(source))

    def test_a_double_underscore_name_is_accepted(self) -> None:
        self.assertEqual([], self._run("def f():\n    __x = g()\n"))


if __name__ == "__main__":
    unittest.main()
