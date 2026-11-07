"""How the consumer walk names a repository file: by its dotted import name,
by the spellings of its path, or by the plugin names it registers.

A symbol is a ``(kind, value)`` pair: :data:`MODULE` with a dotted name,
:data:`NAME` with a plugin name or a group_vars key, :data:`PATH` with a
repository path.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULE = "module"
NAME = "name"
PATH = "path"

PACKAGE_FILES = ("__init__", "__main__")
PLUGIN_CLASSES = {"lookup": "LookupModule", "action": "ActionModule"}


def module_name(path: str) -> str:
    """Return the dotted import name of a repository Python file, empty when
    no import can name it (a role file, a directory with a dash).

    A package's ``__init__`` and ``__main__`` both answer to the package name:
    ``python -m pkg`` runs ``pkg/__main__.py``.

    Args:
        path: repository-relative POSIX path ending in ``.py``.
    """
    parts = path[: -len(".py")].split("/")
    if parts[-1] in PACKAGE_FILES:
        parts = parts[:-1]
    if not parts or any(not part.isidentifier() for part in parts):
        return ""
    return ".".join(parts)


def is_test_file(rel: str) -> bool:
    """Return True for a pytest test module (``test_*.py``).

    Args:
        rel: repository-relative POSIX path.
    """
    name = rel.rpartition("/")[2]
    return name.startswith("test_") and name.endswith(".py")


def path_words(rel: str) -> set[str]:
    """Return the spellings that name *rel* by path anywhere in the tree: the
    repository path and every shorter tail that keeps a directory.

    Args:
        rel: repository-relative POSIX path.
    """
    parts = rel.split("/")
    return {"/".join(parts[index:]) for index in range(max(len(parts) - 1, 1))}


def _dict_keys(node: ast.AST) -> list[str] | None:
    if not isinstance(node, ast.Dict):
        return None
    keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
    return keys if len(keys) == len(node.keys) else None


def plugin_names(rel: str, kind: str, text: str) -> tuple[str, ...] | None:
    """Return the names a plugin file registers; None when they cannot be read.

    A filter file registers the keys of the literal dict its
    ``FilterModule.filters`` returns; a lookup or action file registers its
    stem when it defines the plugin class; a module registers its stem. A
    file without the plugin class is a helper and registers nothing.

    Args:
        rel: repository-relative path of the plugin file.
        kind: ``filter``, ``lookup``, ``action`` or ``module``.
        text: the file's content on the side of the diff being read.
    """
    stem = Path(rel).stem
    if kind == "module":
        return (stem,)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    if kind in PLUGIN_CLASSES:
        return (stem,) if PLUGIN_CLASSES[kind] in classes else ()
    module = classes.get("FilterModule")
    if module is None:
        return ()
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "filters":
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
            keys = [_dict_keys(r.value) for r in returns if r.value]
            if keys and all(k is not None for k in keys):
                return tuple(sorted({name for k in keys for name in k or ()}))
    return None


def start_symbols(rel: str) -> set[tuple[str, str]]:
    """Return the symbols a module or tooling file is named by: a Python file
    by its import name (and its path where no import can name it), any other
    file by its path.

    Args:
        rel: repository-relative POSIX path.
    """
    if not rel.endswith(".py"):
        return {(PATH, rel)}
    dotted = module_name(rel)
    if not dotted:
        return {(PATH, rel)}
    if Path(rel).stem == "__main__":
        return {(MODULE, dotted), (MODULE, f"{dotted}.__main__")}
    return {(MODULE, dotted)}
