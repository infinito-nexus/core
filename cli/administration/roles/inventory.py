"""The inventory files a custom-role pull reads, picked the way Ansible picks them.

A pull stops while any of these files cannot be read: a declaration it
cannot see would make it remove the role as no longer declared.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from yaml import MarkedYAMLError, YAMLError

from cli.administration.inventory.validate.loaders import inventory_files
from utils.cache.yaml import load_yaml_tagged
from utils.inventory.groups import inventory_groups

if TYPE_CHECKING:
    from pathlib import Path

_SKIPPED_NAMES = re.compile(r"^\.|^(?:host_vars|group_vars|vars_plugins)$")
_SKIPPED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".swp",
    ".bak",
    "~",
    ".rpm",
    ".md",
    ".txt",
    ".rst",
    ".orig",
    ".cfg",
    ".retry",
)
_UNREADABLE = (OSError, ValueError, YAMLError)


def is_host_list(inventory: Path) -> bool:
    """Return whether *inventory* is an inline host list such as ``localhost,``.

    Args:
        inventory: the ``-i`` value; Ansible reads it as a host list when
            no such path exists and it holds a comma.
    """
    return "," in str(inventory) and not inventory.exists()


def read_inventory(inventory: Path) -> tuple[dict[str, object], set[str], list[str]]:
    """Read every file of *inventory* the pull takes declarations and groups from.

    Args:
        inventory: an inventory file, or a directory Ansible reads as one:
            its host files, skipped the way Ansible skips them, and the
            ``group_vars``/``host_vars`` beside them.

    Returns:
        ``({file: document}, groups, errors)``; each error names a file
        that cannot be read. Tagged values load as opaque
        :class:`~utils.cache.yaml.TaggedValue` objects.
    """
    if inventory.is_dir():
        base, hosts = inventory, _host_files(inventory)
    else:
        base, hosts = inventory.parent, [inventory]
    documents: dict[str, object] = {}
    errors: list[str] = []
    for path in inventory_files(base):
        try:
            documents[str(path)] = load_yaml_tagged(path)
        except _UNREADABLE as exc:
            errors.append(_unreadable(path, exc))
    groups: set[str] = set()
    for path in hosts:
        try:
            groups |= inventory_groups(str(path))
        except _UNREADABLE as exc:
            if (message := _unreadable(path, exc)) not in errors:
                errors.append(message)
    return documents, groups, errors


def _host_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if _SKIPPED_NAMES.search(entry.name) or entry.name.endswith(_SKIPPED_SUFFIXES):
            continue
        if entry.is_dir():
            files.extend(_host_files(entry))
        elif entry.is_file():
            files.append(entry)
    return files


def _unreadable(path: Path, exc: Exception) -> str:
    if isinstance(exc, UnicodeDecodeError):
        reason = "it is not UTF-8"
    elif isinstance(exc, MarkedYAMLError) and exc.problem_mark is not None:
        reason = f"{exc.problem} at line {exc.problem_mark.line + 1}"
    else:
        reason = str(exc)
    return (
        f"{path}: cannot read the inventory file ({reason}); the pull changes "
        "nothing while an inventory file is unreadable"
    )
