"""Enforce that ``os.environ.get`` names no default value.

A default is a second place the value lives. The deploy already decides what
``OPENWEBUI_ADMIN_NAME`` or ``ADAPTER_PORT`` is and writes it into the
container's environment; repeating it in the reader means the two can drift,
and the copy is the one nobody greps for. ``os.environ["X"]`` fails loudly on
a missing key, which is the behaviour the project wants: a misconfiguration
should stop the run, not silently substitute a guess.

The empty values are free, because they add no second source of truth and
only say "absent". ``""``, ``None``, ``False``, ``0`` and the empty
containers, including the ``"[]"`` and ``"{}"`` a ``json.loads`` reader hands
an absent variable, pass without a marker. A default that is itself an
``os.environ.get`` is free for the same reason: it reads the one source again
under another key rather than naming a value, so nothing can drift. Its own
default is judged separately, so a literal at the end of such a chain is still
reported.

Everything else needs ``# nocheck: environ-get-default`` on the line or
directly above it, naming why that value may not come from the deploy. A
static payload whose container is also run by hand outside Ansible is the
usual honest case.

Detection is on the parsed tree, not on the text, so a call split across lines
is read the same as one written on a single line.
"""

from __future__ import annotations

import ast
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "environ-get-default"
_FREE_SCALARS = ("", None, False, 0)
_FREE_JSON = ("[]", "{}", "()")


def _is_environ_get(node: ast.expr) -> bool:
    """Whether a node is a call to ``os.environ.get``.

    Args:
        node: the node to classify.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "get":
        return False
    owner = func.value
    return isinstance(owner, ast.Attribute) and owner.attr == "environ"


def _is_free(node: ast.expr) -> bool:
    """Whether a default adds no second source of truth.

    Args:
        node: the default argument's node.
    """
    if _is_environ_get(node):
        return True
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        return not (getattr(node, "elts", None) or getattr(node, "keys", None))
    if not isinstance(node, ast.Constant):
        return False
    value = node.value
    if isinstance(value, str):
        return value == "" or value in _FREE_JSON
    return any(value is free for free in _FREE_SCALARS) or value == 0


def _environ_get_defaults(tree: ast.AST) -> list[tuple[int, str]]:
    """Return the line and default of every ``environ.get`` call that has one.

    Args:
        tree: the parsed module.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not _is_environ_get(node) or len(node.args) < 2:
            continue
        default = node.args[1]
        if _is_free(default):
            continue
        found.append((node.lineno, ast.unparse(default)))
    return found


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the defaulted ``environ.get`` calls of one module.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    lines = content.splitlines()
    found: list[str] = []
    for lineno, default in _environ_get_defaults(tree):
        if is_suppressed_at(lines, lineno, _RULE, mode="same-or-above"):
            continue
        found.append(f"{rel_path}:{lineno}: default {default}")
    return found


class TestEnvironGetHasNoDefault(unittest.TestCase):
    def test_no_module_defaults_an_environment_variable(self) -> None:
        offenders: list[str] = []
        for path in iter_project_files(extensions=(".py",)):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if "environ" not in content:
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} call(s) to os.environ.get name a default, which "
            "puts the value in a second place next to the deploy that sets "
            f"it:\n{report}\n\n"
            "Read it with os.environ[...] so a missing key fails loudly, or "
            "keep the default and say why it is not the deploy's to decide "
            f"with `# nocheck: {_RULE} <reason>`.",
        )


class TestDefaultDetection(unittest.TestCase):
    def test_a_value_default_is_reported(self) -> None:
        self.assertEqual(
            ["m.py:1: default 'administrator'"],
            _offenders(
                "m.py", 'import os\nos.environ.get("NAME", "administrator")'[10:]
            ),
        )

    def test_no_default_is_accepted(self) -> None:
        self.assertEqual([], _offenders("m.py", 'os.environ.get("NAME")'))

    def test_a_subscript_read_is_accepted(self) -> None:
        self.assertEqual([], _offenders("m.py", 'os.environ["NAME"]'))

    def test_the_empty_string_is_free(self) -> None:
        self.assertEqual([], _offenders("m.py", 'os.environ.get("NAME", "")'))

    def test_an_empty_json_literal_is_free(self) -> None:
        self.assertEqual(
            [], _offenders("m.py", 'json.loads(os.environ.get("N", "{}"))')
        )

    def test_a_multiline_call_is_still_read(self) -> None:
        source = 'os.environ.get(\n    "NAME",\n    "administrator",\n)'

        self.assertEqual(
            ["m.py:1: default 'administrator'"], _offenders("m.py", source)
        )

    def test_a_chained_environ_read_is_free(self) -> None:
        self.assertEqual(
            [], _offenders("m.py", 'os.environ.get("N", os.environ.get("N_ALT"))')
        )

    def test_a_literal_ending_a_chain_is_still_reported(self) -> None:
        self.assertEqual(
            ["m.py:1: default 'x'"],
            _offenders("m.py", 'os.environ.get("N", os.environ.get("ALT", "x"))'),
        )

    def test_a_nocheck_suppresses_it(self) -> None:
        source = f'os.environ.get("NAME", "administrator")  # nocheck: {_RULE} reason'

        self.assertEqual([], _offenders("m.py", source))


if __name__ == "__main__":
    unittest.main()
