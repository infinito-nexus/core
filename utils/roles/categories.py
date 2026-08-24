"""Category-tree SPOT.

``meta/categories.yml`` at the repository root declares the nested
category tree every role name is derived from: the dash-joined path of a
node is the role's category prefix (``web`` -> ``app`` yields
``web-app-*``), and nodes carry the ``invokable``, ``stage``, ``modes``
and ``run_after`` policy the dispatcher, the stage lookup and the
inventory generator read.

This module owns the file's location and the tree-walking primitives.
Consumers MUST resolve the path through :func:`categories_file` rather
than spelling it themselves, so a future move touches one line.

:data:`FILE_META_CATEGORIES` stays repository-root *relative* and is not
pre-joined onto ``PROJECT_ROOT`` at import time on purpose: the root is
not fixed. ``utils.roles.validation.invokable`` is exercised against a
patched ``PROJECT_ROOT`` and test fixtures build the file inside a
temporary tree. A module level absolute constant would freeze the root at
import time and silently ignore both.

The file is not optional. It lives beside ``roles/``, which the packaging
config excludes from the wheel just as it excludes ``meta/``, so any
context that can resolve a role name also carries this file. A missing
file is a broken checkout and raises rather than degrading to an empty
category tree, which would silently strip every category prefix off every
role name.

Keep this module free of Ansible imports and cheap to import: it is
pulled in by ``plugins/filter/invokable_paths.py``, which runs in
contexts where Ansible is not installed (see
``tests/unit/python/utils/cache/test_data.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from pathlib import Path

FILE_META_CATEGORIES: str = "meta/categories.yml"


def categories_file(root: Path | None = None) -> Path:
    """Absolute path of the category file below *root*.

    Args:
        root: tree to resolve against; the repository root when omitted.
    """
    return (PROJECT_ROOT if root is None else root) / FILE_META_CATEGORIES


def load_categories_tree(categories_file):
    """Return the ``roles`` mapping of the category file.

    Args:
        categories_file: path-like of a ``meta/categories.yml``.
    """
    return load_yaml(categories_file)["roles"]


def flatten_categories(tree, prefix=""):
    """Flattens nested category tree to all possible category paths."""
    result = []
    for k, v in tree.items():
        current = f"{prefix}-{k}" if prefix else k
        result.append(current)
        if isinstance(v, dict):
            for sk, sv in v.items():
                if isinstance(sv, dict):
                    result.extend(flatten_categories({sk: sv}, current))
    return result
