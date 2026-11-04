"""Enforce that ``__all__`` names no type the module merely imported.

Autodoc documents whatever ``__all__`` lists, an imported name included, while
apidoc also writes a page for the submodule the name comes from. The object
then carries two targets, and an annotation naming it resolves to both:
``more than one target found for cross-reference``. The gettext build runs
with ``-W``, so that warning is fatal and the documentation catalogs cannot be
extracted at all.

Only a type can reach that failure, because only a type appears in the
annotations sphinx resolves. Re-exporting a function or a private helper is a
deliberate practice here - ``cli/administration/deploy/development/inventory``
re-exports its helpers so unit tests can patch them under the package path -
and it has never produced a second target. Every entry that did was a class:
``DevInventorySpec``, ``ImageRef``, ``Path``, ``Any``.

A name is read as a type when it is CapWords, which leaves a constant like
``MODES`` or ``LABEL_RE`` alone. The import binds the name either way, so
dropping it from ``__all__`` keeps every importer working and leaves the
object documented once, where it is defined.

A list this check cannot read as literal strings is skipped, because a
computed ``__all__`` names no target of its own. So are the trees apidoc
leaves out, read from ``infinito_docs.commands.APIDOC_EXCLUDED`` rather than
repeated here: a package it never documents cannot carry a second target.

Everything else needs ``# nocheck: all-declares-an-import`` on the line or
directly above it, naming why the package page must carry the type too.
"""

from __future__ import annotations

import ast
import importlib
import sys
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "all-declares-an-import"
_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

_COMMANDS = importlib.import_module("infinito_docs.commands")
_UNDOCUMENTED = tuple(f"{name}/" for name in _COMMANDS.APIDOC_EXCLUDED)


def _statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return the statements that bind a module-level name.

    Args:
        body: the statements of a module or of a block it descends into.
    """
    found: list[ast.stmt] = []
    for node in body:
        found.append(node)
        if isinstance(node, ast.If):
            found.extend(_statements(node.body))
            found.extend(_statements(node.orelse))
        elif isinstance(node, ast.Try):
            found.extend(_statements(node.body))
            found.extend(_statements(node.orelse))
            found.extend(_statements(node.finalbody))
            for handler in node.handlers:
                found.extend(_statements(handler.body))
    return found


def _imported(statements: list[ast.stmt]) -> set[str]:
    """Return the names the module binds by importing them.

    Args:
        statements: the module's name-binding statements.
    """
    names: set[str] = set()
    for node in statements:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _defined(statements: list[ast.stmt]) -> set[str]:
    """Return the names the module defines itself.

    Args:
        statements: the module's name-binding statements.
    """
    names: set[str] = set()
    for node in statements:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _declared(statements: list[ast.stmt]) -> list[tuple[int, str]]:
    """Return the line and value of every literal string in ``__all__``.

    Args:
        statements: the module's name-binding statements.
    """
    found: list[tuple[int, str]] = []
    for node in statements:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        found.extend(
            (element.lineno, element.value)
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return found


def _is_type(name: str) -> bool:
    """Whether a name reads as a class rather than a function or a constant.

    Args:
        name: the name declared in ``__all__``.
    """
    return name[:1].isupper() and not name.isupper()


def _offenders(rel_path: str, content: str) -> list[str]:
    """Return the imported names one module declares in ``__all__``.

    Args:
        rel_path: path relative to the project root.
        content: the file's text.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    statements = _statements(tree.body)
    declared = _declared(statements)
    if not declared:
        return []
    imported = _imported(statements)
    defined = _defined(statements)
    lines = content.splitlines()
    found: list[str] = []
    for lineno, name in declared:
        if name in defined or name not in imported or not _is_type(name):
            continue
        if is_suppressed_at(lines, lineno, _RULE, mode="same-or-above"):
            continue
        found.append(f"{rel_path}:{lineno}: {name}")
    return found


class TestAllDeclaresNoImport(unittest.TestCase):
    def test_no_module_re_exports_through_all(self) -> None:
        offenders: list[str] = []
        for path in iter_project_files(extensions=(".py",)):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if rel.startswith(_UNDOCUMENTED):
                continue
            try:
                content = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if "__all__" not in content:
                continue
            offenders.extend(_offenders(rel, content))

        report = "\n".join(f"  - {o}" for o in sorted(offenders))
        self.assertFalse(
            offenders,
            f"{len(offenders)} type(s) in an __all__ are only imported, so sphinx "
            "documents them on the package page as well as on the page of the "
            "module that defines them and every annotation naming one resolves "
            f"to two targets:\n{report}\n\n"
            "Drop the entry, which keeps the type importable because the import "
            "binds it anyway, or say why the package page must carry it too "
            f"with `# nocheck: {_RULE} <reason>`.",
        )


class TestReExportDetection(unittest.TestCase):
    def test_an_imported_name_is_reported(self) -> None:
        source = 'from .model import Mesh\n\n__all__ = [\n    "Mesh",\n]'

        self.assertEqual(["m.py:4: Mesh"], _offenders("m.py", source))

    def test_a_defined_type_is_accepted(self) -> None:
        source = 'class Mesh:\n    pass\n\n__all__ = ["Mesh"]'

        self.assertEqual([], _offenders("m.py", source))

    def test_an_imported_function_is_accepted(self) -> None:
        source = 'from .plan import plan_mesh\n\n__all__ = ["plan_mesh"]'

        self.assertEqual([], _offenders("m.py", source))

    def test_an_imported_private_helper_is_accepted(self) -> None:
        source = 'from .r import _resolve\n\n__all__ = ["_resolve"]'

        self.assertEqual([], _offenders("m.py", source))

    def test_an_imported_constant_is_accepted(self) -> None:
        source = 'from .axes import MODES, LABEL_RE\n\n__all__ = ["MODES", "LABEL_RE"]'

        self.assertEqual([], _offenders("m.py", source))

    def test_a_name_both_imported_and_defined_is_accepted(self) -> None:
        source = 'from .a import Mesh\n\nclass Mesh:\n    pass\n\n__all__ = ["Mesh"]'

        self.assertEqual([], _offenders("m.py", source))

    def test_an_aliased_import_is_reported_under_its_alias(self) -> None:
        source = 'from .model import Mesh as Grid\n\n__all__ = ["Grid"]'

        self.assertEqual(["m.py:3: Grid"], _offenders("m.py", source))

    def test_a_third_party_type_is_reported(self) -> None:
        source = 'from pathlib import Path\n\n__all__ = ["Path"]'

        self.assertEqual(["m.py:3: Path"], _offenders("m.py", source))

    def test_a_type_checking_import_is_still_an_import(self) -> None:
        source = (
            "from typing import TYPE_CHECKING\n\n"
            "if TYPE_CHECKING:\n    from .model import Mesh\n\n"
            '__all__ = ["Mesh"]'
        )

        self.assertEqual(["m.py:6: Mesh"], _offenders("m.py", source))

    def test_a_computed_all_is_skipped(self) -> None:
        source = "from .m import x\n\n__all__ = public_names(m)"

        self.assertEqual([], _offenders("m.py", source))

    def test_a_module_without_all_is_skipped(self) -> None:
        self.assertEqual([], _offenders("m.py", "from .model import Mesh"))

    def test_a_nocheck_suppresses_it(self) -> None:
        source = (
            "from .model import Mesh\n\n__all__ = [\n"
            f'    "Mesh",  # nocheck: {_RULE} reason\n]'
        )

        self.assertEqual([], _offenders("m.py", source))


if __name__ == "__main__":
    unittest.main()
