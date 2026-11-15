"""Enforce that no check and no helper a check reads skips a custom role.

A role an inventory pulls into ``roles/web-app-cst-*`` is verified exactly like
an in-tree role. A loop that steps over it with
``if is_custom(role): continue``, a comprehension that keeps only
``not is_custom(...)`` entries, or a ``skipIf`` keyed on the prefix would let a
pulled role pass a check the in-tree roles must pass.

The sanctioned exception is the i18n extraction: ``role_messages`` and
``rbac_messages`` in ``utils/i18n/extract.py`` leave a custom role's
descriptions out of the core catalogs, which Git tracks while the role itself
is ignored. The unit test of the back-channel README table is sanctioned as
well: it swaps whatever custom role is placed for a synthetic one, so the rule
it tests sees a known declaration, while the lint it tests still reads every
placed role.

The scan covers ``tests/``, ``utils/`` and ``plugins/`` and is done on the
parsed tree: a custom-role predicate is a call to ``is_custom`` or
``is_custom_path``, or a string literal naming the ``web-app-cst`` prefix.
"""

from __future__ import annotations

import ast
import unittest

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

_SCOPES = ("tests/", "utils/", "plugins/")
_PREDICATES = frozenset({"is_custom", "is_custom_path"})
_PREFIX_LITERAL = "web-app-cst"
_SKIP_CALLS = frozenset({"skipTest", "skip", "skipIf", "skipUnless"})
_SANCTIONED = frozenset(
    {
        ("utils/i18n/extract.py", "role_messages"),
        ("utils/i18n/extract.py", "rbac_messages"),
        (
            "tests/unit/python/roles/web-svc-logout/test_readme_backchannel_table.py",
            "setUp",
        ),
    }
)


def _name_of(func: ast.expr) -> str:
    """Return the called name of a call's ``func`` node.

    Args:
        func: the ``func`` of an ``ast.Call``.
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _names_custom_role(node: ast.AST) -> bool:
    """Whether an expression asks if something is a custom role.

    Args:
        node: the expression to inspect.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _name_of(child.func) in _PREDICATES:
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and _PREFIX_LITERAL in child.value
        ):
            return True
    return False


def _negates_custom_role(node: ast.AST) -> bool:
    """Whether a filter keeps only what is not a custom role.

    Args:
        node: the ``if`` clause of a comprehension.
    """
    return any(
        isinstance(child, ast.UnaryOp)
        and isinstance(child.op, ast.Not)
        and _names_custom_role(child.operand)
        for child in ast.walk(node)
    )


def _leaves(statement: ast.stmt) -> bool:
    """Whether a statement ends the current item without checking it.

    Args:
        statement: the first statement of an ``if`` body.
    """
    if isinstance(statement, (ast.Continue, ast.Return)):
        return True
    if isinstance(statement, ast.Raise) and statement.exc is not None:
        target = statement.exc
        target = target.func if isinstance(target, ast.Call) else target
        return _name_of(target) == "SkipTest"
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _name_of(statement.value.func) in _SKIP_CALLS
    )


class _SkipFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []
        self._functions: list[str] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and _name_of(decorator.func) in _SKIP_CALLS
                and _names_custom_role(decorator)
            ):
                self.found.append((decorator.lineno, node.name))
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _where(self) -> str:
        return self._functions[-1] if self._functions else "<module>"

    def visit_If(self, node: ast.If) -> None:
        if _names_custom_role(node.test) and node.body and _leaves(node.body[0]):
            self.found.append((node.lineno, self._where()))
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        for clause in node.ifs:
            if _negates_custom_role(clause):
                self.found.append((clause.lineno, self._where()))
        self.generic_visit(node)


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the custom-role skips of one module outside the sanctioned ones.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    finder = _SkipFinder()
    finder.visit(tree)
    return [
        f"{rel_path}:{lineno}: {function}"
        for lineno, function in finder.found
        if (rel_path, function) not in _SANCTIONED
    ]


class TestCustomRolesNeverSkipped(unittest.TestCase):
    def test_no_check_skips_a_custom_role(self) -> None:
        offenders: list[str] = []
        for path in iter_non_ignored_files(extensions=(".py",)):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if not rel.startswith(_SCOPES):
                continue
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if _PREFIX_LITERAL not in content and "is_custom" not in content:
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} place(s) skip a roles/web-app-cst-* role, which "
            f"core verifies like every in-tree role:\n{report}\n\n"
            "Check the custom role like any other. Only the i18n extraction "
            "(role_messages, rbac_messages in utils/i18n/extract.py) may leave "
            "it out.",
        )


class TestSkipDetection(unittest.TestCase):
    def test_a_loop_that_continues_past_a_custom_role_is_reported(self) -> None:
        source = "def scan(roles):\n    for r in roles:\n        if is_custom(r):\n            continue\n"

        self.assertEqual(["m.py:3: scan"], _offenders("m.py", source))

    def test_a_prefix_literal_guarding_a_return_is_reported(self) -> None:
        source = 'def one(r):\n    if r.startswith("web-app-cst-"):\n        return\n'

        self.assertEqual(["m.py:2: one"], _offenders("m.py", source))

    def test_a_comprehension_keeping_only_in_tree_roles_is_reported(self) -> None:
        source = "names = [n for n in roles if n and not is_custom(n)]\n"

        self.assertEqual(["m.py:1: <module>"], _offenders("m.py", source))

    def test_a_skip_decorator_keyed_on_the_prefix_is_reported(self) -> None:
        source = (
            "class T:\n"
            '    @unittest.skipIf(ROLE.startswith("web-app-cst-"), "custom")\n'
            "    def test_x(self):\n"
            "        pass\n"
        )

        self.assertEqual(["m.py:2: test_x"], _offenders("m.py", source))

    def test_a_skip_test_call_is_reported(self) -> None:
        source = "def test_x(self, r):\n    if is_custom_path(r):\n        self.skipTest('custom')\n"

        self.assertEqual(["m.py:2: test_x"], _offenders("m.py", source))

    def test_including_a_custom_role_is_accepted(self) -> None:
        source = "keep = {p for p in paths if is_custom_path(p)}\n"

        self.assertEqual([], _offenders("m.py", source))

    def test_asserting_the_predicate_is_accepted(self) -> None:
        source = 'def test_x(self):\n    self.assertTrue(is_custom("web-app-cst-a"))\n'

        self.assertEqual([], _offenders("m.py", source))

    def test_refusing_a_non_custom_role_is_accepted(self) -> None:
        source = "def run(a):\n    if not is_custom(a):\n        raise ValueError(a)\n"

        self.assertEqual([], _offenders("m.py", source))

    def test_the_i18n_extraction_is_sanctioned(self) -> None:
        source = "def role_messages(root):\n    for r in roles:\n        if is_custom(r):\n            continue\n"

        self.assertEqual([], _offenders("utils/i18n/extract.py", source))
        self.assertEqual(
            ["utils/other.py:3: role_messages"],
            _offenders("utils/other.py", source),
        )


if __name__ == "__main__":
    unittest.main()
