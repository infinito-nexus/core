"""The marker that identifies a custom role the pull placed under ``roles/``.

The marker names the directory it was placed as, so a copy of a placed
role under another name, which carries the same file, never counts as
placed. It is written and read without following a symbolic link.
"""

from __future__ import annotations

import os
import shutil
import stat
from typing import TYPE_CHECKING

from utils.roles.custom import PREFIX

if TYPE_CHECKING:
    from pathlib import Path

MARKER_FILE = ".infinito-custom-role"
MARKER_HEADER = "# infinito-nexus custom role"
_MARKER_LIMIT = 4096


def marker_text(directory: str, group: str, provenance: str) -> str:
    """Return the content of the marker file.

    Args:
        directory: the name the role directory is placed as under ``roles/``.
        group: the inventory group the role was pulled for.
        provenance: the source and resolved commit the role was placed from.
    """
    return (
        f"{MARKER_HEADER}\ndirectory: {directory}\ngroup: {group}\n"
        f"source: {provenance}\n"
    )


def write_marker(role: Path, group: str, provenance: str) -> None:
    """Write the marker into a staged role, replacing whatever entry holds its name.

    The entry is removed without following it and the marker is created
    exclusively, so a symbolic link shipped under that name never
    redirects the write.

    Args:
        role: the staged role directory, named as it is placed.
        group: the inventory group the role was pulled for.
        provenance: the source and resolved commit the role was placed from.
    """
    marker = role / MARKER_FILE
    try:
        mode = marker.lstat().st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None and stat.S_ISDIR(mode):
        shutil.rmtree(marker)
    elif mode is not None:
        marker.unlink()
    descriptor = os.open(
        marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(marker_text(role.name, group, provenance))


def is_placed(path: Path) -> bool:
    """Return whether the pull placed ``path``: its marker names ``path`` itself.

    Args:
        path: an entry of the role search directory.
    """
    return not path.is_symlink() and _fields(path).get("directory") == path.name


def provenance(path: Path) -> str:
    """Return the source and resolved commit recorded for a placed role.

    Args:
        path: a role directory :func:`is_placed` accepts.
    """
    return _fields(path).get("source", "")


def custom_entries(roles_dir: Path) -> list[Path]:
    """Return every ``roles/web-app-cst-*`` entry, placed or not, sorted.

    Args:
        roles_dir: the role search directory.
    """
    return sorted(roles_dir.glob(f"{PREFIX}*"))


def placed_roles(roles_dir: Path) -> list[Path]:
    """Return the custom roles the pull placed under ``roles_dir``, sorted.

    Args:
        roles_dir: the role search directory.
    """
    return [entry for entry in custom_entries(roles_dir) if is_placed(entry)]


def _fields(role: Path) -> dict[str, str]:
    # Exception: O_NONBLOCK keeps a FIFO planted under the marker name from
    # blocking the open; the fstat below refuses it.
    try:
        descriptor = os.open(
            role / MARKER_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
    except OSError:
        return {}
    with os.fdopen(descriptor, encoding="utf-8", errors="replace") as handle:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return {}
        lines = handle.read(_MARKER_LIMIT).splitlines()
    if not lines or lines[0] != MARKER_HEADER:
        return {}
    return dict(line.split(": ", 1) for line in lines[1:] if ": " in line)
