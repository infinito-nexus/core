from __future__ import annotations

import ast
import re
from functools import lru_cache

from tests.lint.repository import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text

__all__ = [
    "ACCEPTABLE_UNUSED",
    "PROJECT_ROOT",
    "declared_all",
    "module_level",
    "python_modules",
    "read_names",
]

ACCEPTABLE_UNUSED = re.compile(r"_+|__.*|.*unused.*|.*dummy.*|empty")
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


@lru_cache(maxsize=1)
def python_modules() -> tuple[tuple[str, str, ast.Module], ...]:
    """Return every project Python file that parses, read and parsed once.

    Returns:
        ``(path relative to the project root, text, tree)`` per file.
    """
    found: list[tuple[str, str, ast.Module]] = []
    for path in iter_project_files(extensions=(".py",)):
        rel = str(path).replace(f"{PROJECT_ROOT}/", "")
        try:
            content = read_text(str(path))
            tree = ast.parse(content)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        found.append((rel, content, tree))
    return tuple(found)


def module_level(body: list[ast.stmt]) -> list[ast.stmt]:
    """Return the statements that run in the module's own scope.

    Args:
        body: the statements of the module or of a block it descends into.
    """
    found: list[ast.stmt] = []
    for node in body:
        if isinstance(node, _SCOPES):
            continue
        found.append(node)
        for field in ("body", "orelse", "finalbody"):
            found.extend(module_level(getattr(node, field, None) or []))
        for handler in getattr(node, "handlers", None) or []:
            found.extend(module_level(handler.body))
    return found


def declared_all(tree: ast.Module, statements: list[ast.stmt]) -> set[str] | None:
    """Return the literal ``__all__`` of a module, ``None`` when it is computed.

    Args:
        tree: the parsed module.
        statements: its module-level statements.
    """
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "__all__"
        ):
            return None
    names: set[str] = set()
    for node in statements:
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        if not isinstance(node, ast.Assign) or not isinstance(
            node.value, (ast.List, ast.Tuple)
        ):
            return None
        for element in node.value.elts:
            if not isinstance(element, ast.Constant):
                return None
            names.add(element.value)
    return names


def read_names(tree: ast.Module, content: str) -> set[str]:
    """Return every name the module reads, string annotations and type comments included.

    Args:
        tree: the parsed module.
        content: the module's text.
    """
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store)
    }
    annotations: list[ast.expr] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.arg) and node.annotation is not None) or isinstance(
            node, ast.AnnAssign
        ):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            annotations.append(node.returns)
    for annotation in annotations:
        for leaf in ast.walk(annotation):
            if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
                names.update(_IDENTIFIER.findall(leaf.value))
    for line in content.splitlines():
        if "# type:" in line:
            names.update(_IDENTIFIER.findall(line.split("# type:", 1)[1]))
    return names
