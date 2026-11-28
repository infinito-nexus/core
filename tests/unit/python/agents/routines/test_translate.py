"""Unit test: the translation routine runs translation through ``cli/build/i18n``
and carries no copy of its logic. Every ``i18n-*`` make target a step names
exists and its recipe runs ``python -m cli.build.i18n``, and the routine module
defines no function besides ``build`` and imports nothing besides the routine
contract."""

from __future__ import annotations

import ast
import re
import unittest

from agents.routines import translate
from utils.cache.files import PROJECT_ROOT, read_text

_TARGET = re.compile(r"\bi18n-[a-z]+\b")
_CLI = '"$${PYTHON}" -m cli.build.i18n '
_MAKEFILE = PROJECT_ROOT / "Makefile"
_ROUTINE = PROJECT_ROOT / "agents" / "routines" / "translate.py"


def named_targets(labels: list[str]) -> list[str]:
    """Return the ``i18n-*`` make targets the step labels name, in order.

    Args:
        labels: the routine's step labels.
    """
    found: list[str] = []
    for label in labels:
        found.extend(t for t in _TARGET.findall(label) if t not in found)
    return found


def recipe(makefile: str, target: str) -> str:
    """Return the recipe lines of ``target`` in ``makefile``, joined.

    Args:
        makefile: the Makefile text.
        target: the make target.
    """
    lines = makefile.splitlines()
    start = lines.index(f"{target}:")
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    return "\n".join(body)


def foreign_logic(source: str) -> list[str]:
    """Return what in a routine module goes beyond the contract: a function
    other than ``build`` or an import from outside ``agents.routines.contract``
    and ``__future__``.

    Args:
        source: the routine module's source.
    """
    found: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name != "build":
                found.append(node.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module not in ("__future__", "agents.routines.contract"):
                found.append(f"from {node.module}")
        elif isinstance(node, ast.Import):
            found.extend(f"import {alias.name}" for alias in node.names)
    return found


class TestTranslateRoutine(unittest.TestCase):
    def test_the_steps_name_the_i18n_targets(self) -> None:
        targets = named_targets([step.label for step in translate.STEPS])
        self.assertEqual(
            targets, ["i18n-extract", "i18n-prune", "i18n-translate", "i18n-retry"]
        )

    def test_every_named_target_runs_cli_build_i18n(self) -> None:
        makefile = read_text(str(_MAKEFILE))
        for target in named_targets([step.label for step in translate.STEPS]):
            with self.subTest(target=target):
                subcommand = target.removeprefix("i18n-")
                self.assertIn(f"{_CLI}{subcommand}", recipe(makefile, target))

    def test_the_routine_holds_no_copy_of_the_logic(self) -> None:
        self.assertEqual(foreign_logic(read_text(str(_ROUTINE))), [])

    def test_a_copied_function_is_found(self) -> None:
        source = (
            "from __future__ import annotations\n"
            "from utils.i18n import catalogs\n"
            "def translate_catalog(path):\n    return path\n"
            "def build():\n    return None\n"
        )
        self.assertEqual(
            foreign_logic(source), ["from utils.i18n", "translate_catalog"]
        )

    def test_a_target_outside_cli_build_i18n_is_found(self) -> None:
        makefile = "i18n-translate:\n\t@bash scripts/i18n/own.sh\n"
        self.assertNotIn(f"{_CLI}translate", recipe(makefile, "i18n-translate"))


if __name__ == "__main__":
    unittest.main()
