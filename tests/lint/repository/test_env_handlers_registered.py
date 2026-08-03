"""Every env handler on disk must appear in the registry that runs them.

``build_env()`` iterates ``ORDERED_HANDLERS`` from
``utils/env/handlers/__init__.py``; a module the list omits never runs, so the
key it owns is simply absent from the generated .env. Nothing fails - the
consumer reads an empty value and behaves as if the feature were switched off.

Parsed rather than imported: one handler pulls a third-party dependency at
import time, and a registry check must not depend on the environment it
describes.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

HANDLERS = PROJECT_ROOT / "utils" / "env" / "handlers"
REGISTRY = HANDLERS / "__init__.py"


def _parse(path):
    return ast.parse(read_text(str(path)))


def _registry():
    """Map the alias each handler is imported under to its module path."""
    tree = _parse(REGISTRY)
    aliases: dict[str, str] = {}
    ordered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            prefix = f"{node.module}." if node.module else ""
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{prefix}{alias.name}"
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ORDERED_HANDLERS" for t in node.targets
        ):
            ordered = {e.id for e in node.value.elts if isinstance(e, ast.Name)}
    return aliases, ordered


def _modules_with_apply():
    for path_str in iter_project_files(extensions=(".py",)):
        path = Path(path_str)
        if not path.is_relative_to(HANDLERS) or path.name == "__init__.py":
            continue
        tree = _parse(path)
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "apply"
            for node in tree.body
        ):
            yield ".".join(path.relative_to(HANDLERS).with_suffix("").parts)


class TestEnvHandlersRegistered(unittest.TestCase):
    def setUp(self) -> None:
        self.aliases, self.ordered = _registry()
        self.registered = {self.aliases[name] for name in self.ordered}

    def test_every_handler_module_is_registered(self) -> None:
        missing = sorted(set(_modules_with_apply()) - self.registered)
        if missing:
            self.fail(
                f"{len(missing)} env handler(s) define apply() but are absent from "
                "ORDERED_HANDLERS, so their keys never reach the generated .env:\n"
                + "\n".join(
                    f"  utils/env/handlers/{m.replace('.', '/')}.py" for m in missing
                )
            )

    def test_every_registered_name_resolves_to_a_module(self) -> None:
        unresolved = sorted(self.ordered - set(self.aliases))
        self.assertEqual(unresolved, [])

    def test_the_registry_is_not_empty(self) -> None:
        self.assertGreater(len(self.registered), 20)


if __name__ == "__main__":
    unittest.main()
