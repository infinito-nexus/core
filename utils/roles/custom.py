"""Custom-role naming SPOT.

A custom role is the inventory group ``web-app-cst-<name>``. Its
``applications.<group>`` block marks it with ``custom: true`` and names
the repository it comes from under ``source``. The pull places it as
``roles/<group>``, which ``.gitignore`` keeps out of every core commit.

Keep this module free of imports beyond the standard library: the
project-tree scan helpers in :mod:`utils.cache` read it.
"""

from __future__ import annotations

PREFIX: str = "web-app-cst-"
ROLES_GLOB: str = f"roles/{PREFIX}*"
CUSTOM_KEY: str = "custom"
SOURCE_KEY: str = "source"


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
