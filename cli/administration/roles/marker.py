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

from utils.roles.custom import MARKER_FILE, MARKER_HEADER, PREFIX, marker_fields

if TYPE_CHECKING:
    from pathlib import Path


def marker_text(directory: str, group: str, provenance: str, version: str) -> str:
    """Return the content of the marker file.

    Args:
        directory: the name the role directory is placed as under ``roles/``.
        group: the inventory group the role was pulled for.
        provenance: the source and resolved commit the role was placed from.
        version: the semver the source's manifests declare; empty for none.
    """
    text = (
        f"{MARKER_HEADER}\ndirectory: {directory}\ngroup: {group}\n"
        f"source: {provenance}\n"
    )
    return f"{text}version: {version}\n" if version else text


def write_marker(role: Path, group: str, provenance: str, version: str) -> None:
    """Write the marker into a staged role, replacing whatever entry holds its name.

    The entry is removed without following it and the marker is created
    exclusively, so a symbolic link shipped under that name never
    redirects the write.

    Args:
        role: the staged role directory, named as it is placed.
        group: the inventory group the role was pulled for.
        provenance: the source and resolved commit the role was placed from.
        version: the semver the source's manifests declare; empty for none.
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
        marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(marker_text(role.name, group, provenance, version))


def is_placed(path: Path) -> bool:
    """Return whether the pull placed ``path``: its marker names ``path`` itself.

    Args:
        path: an entry of the role search directory.
    """
    return not path.is_symlink() and marker_fields(path).get("directory") == path.name


def provenance(path: Path) -> str:
    """Return the source and resolved commit recorded for a placed role.

    Args:
        path: a role directory :func:`is_placed` accepts.
    """
    return marker_fields(path).get("source", "")


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
