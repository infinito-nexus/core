"""The directory names of the roles, as one source for every reader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

ROLES_DIR = "roles"


@lru_cache(maxsize=1)
def role_names(root: str = str(PROJECT_ROOT)) -> tuple[str, ...]:
    """Return every role directory name, sorted.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    return tuple(
        sorted(path.name for path in Path(root, ROLES_DIR).iterdir() if path.is_dir())
    )
