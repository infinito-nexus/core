"""The title a role presents itself under.

A role declares it twice and the two may differ: the ``README.md`` heading is
what a reader sees, ``galaxy_info.name`` what the metadata carries. The heading
wins where both exist, because the documentation is built from it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.meta.role.names import ROLES_DIR
from utils.roles.mapping import ROLE_FILE_META_MAIN

README = "README.md"


def role_title(role_dir: Path) -> str:
    """Return the title ``role_dir`` declares, empty when it declares none.

    Args:
        role_dir: the role's directory.
    """
    readme = role_dir / README
    if readme.is_file():
        for line in read_text(str(readme)).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    meta = role_dir / ROLE_FILE_META_MAIN
    if meta.is_file():
        declared = (load_yaml(str(meta)) or {}).get("galaxy_info") or {}
        if declared.get("name"):
            return str(declared["name"]).strip()
    return ""


@lru_cache(maxsize=1)
def role_titles(root: str = str(PROJECT_ROOT)) -> tuple[str, ...]:
    """Return every declared role title, sorted and without duplicates.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    found = set()
    for path in sorted(Path(root, ROLES_DIR).iterdir()):
        if not path.is_dir():
            continue
        title = role_title(path)
        if title:
            found.add(title)
    return tuple(sorted(found))
