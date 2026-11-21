"""Custom-role naming SPOT.

A custom role is the inventory group ``web-app-cst-<name>``. Its
``applications.<group>`` block marks it with ``custom: true`` and names
the repository it comes from under ``source``. The pull places it as
``roles/<group>``, which ``.gitignore`` keeps out of every core commit.

Keep this module free of imports beyond the standard library: the
project-tree scan helpers in :mod:`utils.cache` read it.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PREFIX: str = "web-app-cst-"
ROLES_GLOB: str = f"roles/{PREFIX}*"
CUSTOM_KEY: str = "custom"
SOURCE_KEY: str = "source"
MANIFEST_FILE: str = "meta/custom_roles.yml"
MANIFEST_COMMIT_KEY: str = "commit"
RELEASE_TAG: re.Pattern[str] = re.compile(r"v?\d+\.\d+\.\d+", re.ASCII)
MARKER_FILE: str = ".infinito-custom-role"
MARKER_HEADER: str = "# infinito-nexus custom role"
VERSION_MANIFESTS: tuple[str, ...] = ("Cargo.toml", "pyproject.toml", "package.json")

_MARKER_LIMIT = 4096
_SEMVER = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?", re.ASCII)
_ROLE_VERSION_LOOKUP = re.compile(
    r"\{\{\s*lookup\(\s*(['\"])role_version\1\s*,\s*(['\"])(?P<role>[^'\"]+)\2\s*\)\s*\}\}"
)


class CustomRoleError(Exception):
    """A custom-role declaration, fetch or placement that stops the run."""


def is_custom(name: str) -> bool:
    """Whether *name* carries the reserved custom-role prefix.

    Args:
        name: a role directory, inventory group or application_id.
    """
    return name.startswith(PREFIX)


def is_custom_path(rel_path: str) -> bool:
    """Whether a repository-relative POSIX path lies in a placed custom role.

    Args:
        rel_path: path relative to the repository root, ``/``-separated.
    """
    parts = rel_path.split("/")
    return len(parts) > 1 and parts[0] == "roles" and is_custom(parts[1])


def marker_fields(role: Path) -> dict[str, str]:
    """Return the fields of a role's pull marker, read without following a link.

    Args:
        role: a role directory under ``roles/``.

    Returns:
        ``directory``, ``group``, ``source`` and, when the pull found one,
        ``version``; empty when the role carries no readable marker.
    """
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


def resolve_role_version(value: str, roles_dir: Path) -> str:
    """Replace each ``{{ lookup('role_version', '<id>') }}`` with the version the pull recorded.

    Args:
        value: a ``meta/services.yml`` field, e.g.
            ``v{{ lookup('role_version', 'web-app-cst-store') }}``.
        roles_dir: the ``roles/`` directory holding the pulled role.

    Returns:
        *value* with every lookup whose role marker carries a version replaced
        by it; a lookup without one stays as written.
    """
    return _ROLE_VERSION_LOOKUP.sub(
        lambda match: (
            marker_fields(roles_dir / match["role"]).get("version") or match[0]
        ),
        value,
    )


def manifest_version(read: Callable[[str], str | None]) -> str:
    """Return the semver the first version manifest of a repository declares.

    Args:
        read: returns the text of a file at the repository root by name, or
            None when the repository has no such file.

    Returns:
        ``[package].version`` of ``Cargo.toml`` (or its
        ``[workspace.package].version``), ``[project].version`` of
        ``pyproject.toml`` or ``version`` of ``package.json``, tried in
        that order; a value that is no semver is passed over. Empty when
        none declares one.
    """
    for name in VERSION_MANIFESTS:
        text = read(name)
        if text is None:
            continue
        version = _declared_version(name, text)
        if _SEMVER.fullmatch(version):
            return version
    return ""


def _declared_version(name: str, text: str) -> str:
    try:
        data = json.loads(text) if name == "package.json" else tomllib.loads(text)
    except (ValueError, RecursionError):
        return ""
    if not isinstance(data, dict):
        return ""
    if name == "package.json":
        candidates = [data]
    elif name == "Cargo.toml":
        workspace = data.get("workspace")
        candidates = [
            data.get("package"),
            workspace.get("package") if isinstance(workspace, dict) else None,
        ]
    else:
        candidates = [data.get("project")]
    for table in candidates:
        value = table.get("version") if isinstance(table, dict) else None
        if isinstance(value, str):
            return value
    return ""
