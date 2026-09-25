"""The role titles that name an upstream product rather than describe a job.

``Mastodon`` must survive translation, ``Cleanup Disc Space`` must not. Neither
the capital nor a dictionary separates them: a brand is deliberately built from
an ordinary word, so ``Mastodon``, ``Matrix``, ``Cursor`` and ``Shell`` all sit
in an English dictionary, while a descriptive title regularly carries a term no
dictionary holds. Measured against en_US-large, that rule would have released
Mastodon, PostgreSQL and WordPress for translation and protected ``Automated
Email Alerts for Service Failures``.

What does separate them is the role's own account of what it deploys: the
upstream homepage and the image it pulls. ``Mastodon`` sits inside
``joinmastodon.org``; ``Cleanup Disc Space`` sits inside nothing. Every word of
the title must appear, not the title as one string, because a product spells
its parts in either order: ``Claude Code`` lives at ``code.claude.com``.

Only those two fields are read. Matching against every URL in the role sweeps in
whatever its prose links to, and a reference to ``en.wikipedia.org/wiki/
Bourne_shell`` then turns ``Shell`` into a brand.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.meta.role.names import ROLES_DIR
from utils.meta.role.titles import role_title
from utils.roles.mapping import ROLE_FILE_META_INFO, ROLE_FILE_META_SERVICES

UPSTREAM_KEYS = ("image", "repository")


def squashed(text: str) -> str:
    """Return ``text`` reduced to its letters and digits, lower case."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def upstream(role_dir: Path) -> str:
    """Return the identifiers ``role_dir`` names its upstream product by.

    Args:
        role_dir: the role's directory.
    """
    parts = []
    info = role_dir / ROLE_FILE_META_INFO
    if info.is_file():
        parts.append(str((load_yaml(str(info)) or {}).get("homepage") or ""))
    services = role_dir / ROLE_FILE_META_SERVICES
    if services.is_file():
        for entry in (load_yaml(str(services)) or {}).values():
            if isinstance(entry, dict):
                parts += [str(entry.get(key) or "") for key in UPSTREAM_KEYS]
    return squashed(" ".join(parts))


def is_brand(title: str, role_dir: Path) -> bool:
    """Whether ``title`` names the product ``role_dir`` deploys.

    Args:
        title: the role's declared title.
        role_dir: the role's directory.
    """
    words = [squashed(part) for part in re.split(r"[^A-Za-z0-9]+", title)]
    words = [word for word in words if word]
    if not words:
        return False
    marks = upstream(role_dir)
    return bool(marks) and all(word in marks for word in words)


@lru_cache(maxsize=1)
def brand_titles(root: str = str(PROJECT_ROOT)) -> tuple[str, ...]:
    """Return every role title that names an upstream product, sorted.

    Args:
        root: repository root, as a string so the cache key stays hashable.
    """
    found = set()
    for path in sorted(Path(root, ROLES_DIR).iterdir()):
        if not path.is_dir():
            continue
        title = role_title(path)
        if title and is_brand(title, path):
            found.add(title)
    return tuple(sorted(found))
