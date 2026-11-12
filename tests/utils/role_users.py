"""Reading the users a role declares in its role-meta users file."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_USERS

if TYPE_CHECKING:
    from pathlib import Path

_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+):")


def declared_users(role_dir: Path) -> set[str]:
    """User keys a role declares.

    Args:
        role_dir: the role directory.

    Returns:
        Top-level keys of its role-meta users file, empty when it is absent.
    """
    users_file = role_dir / ROLE_FILE_META_USERS
    if not users_file.is_file():
        return set()
    return {
        match.group(1)
        for match in (
            _TOP_LEVEL_KEY.match(line)
            for line in read_text(str(users_file)).splitlines()
        )
        if match
    }


def declared_universe(roles_dir: Path) -> set[str]:
    """Every user key any role declares.

    Args:
        roles_dir: the roles directory.

    Returns:
        Union of all roles' declared user keys.
    """
    universe: set[str] = set()
    for role_dir in roles_dir.iterdir():
        if role_dir.is_dir():
            universe |= declared_users(role_dir)
    return universe
