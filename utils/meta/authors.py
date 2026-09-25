"""The people the repository credits, as one source for every reader.

The names are derived from the ``## Credits`` sections themselves rather than
kept as a list, so crediting a contributor needs no code change. The derivation
lives in :mod:`utils.roles.credits`; this module is the entry point for readers
that want the names alone.
"""

from __future__ import annotations

from functools import lru_cache

from utils.roles.credits import author_urls


@lru_cache(maxsize=1)
def author_names() -> tuple[str, ...]:
    """Return every credited person's name, sorted."""
    return tuple(sorted(author_urls()))
