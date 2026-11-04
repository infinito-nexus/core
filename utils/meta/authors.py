"""The people the roles name as their authors.

``galaxy_info.author`` is where a role records who implemented it, so that is
where the names are read. A role may credit more than one person, comma
separated.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.meta.role.names import ROLES_DIR
from utils.roles.mapping import ROLE_FILE_META_MAIN


def role_authors(role_dir: Path) -> tuple[str, ...]:
    """Return the people ``role_dir`` names as its authors.

    Args:
        role_dir: the role's directory.
    """
    meta = role_dir / ROLE_FILE_META_MAIN
    if not meta.is_file():
        return ()
    declared = ((load_yaml(str(meta)) or {}).get("galaxy_info") or {}).get("author")
    if not declared:
        return ()
    return tuple(part.strip() for part in str(declared).split(",") if part.strip())


@lru_cache(maxsize=1)
def author_names(root: str = str(PROJECT_ROOT)) -> tuple[str, ...]:
    """Return every declared role author, sorted and without duplicates.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    found = set()
    for path in sorted(Path(root, ROLES_DIR).iterdir()):
        if path.is_dir():
            found.update(role_authors(path))
    return tuple(sorted(found))
