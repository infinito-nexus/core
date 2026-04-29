"""Gitignore-aware path matching for project-tree scans.

SPOT for the fnmatch-based ``.gitignore``-style filter used by lint and
integration tests that need to walk the repository without spawning
``git``. Covers the shapes the repo's ``.gitignore`` actually uses
(basename patterns, path-qualified patterns, trailing-slash-as-directory)
and intentionally omits negation (``!``) and ``**`` globstar — adding
either would require a real pathspec implementation.

Public API:

* :func:`load_gitignore_patterns` — read non-empty, non-comment,
  non-negated lines from ``<root>/.gitignore``. Cached process-wide.
* :func:`is_path_gitignored` — pure matcher: does a repo-relative
  POSIX-style path match any of the supplied patterns?

The combined "yield project files filtered through ``.gitignore``"
helper lives in :mod:`utils.cache.files` (``iter_non_ignored_files``)
because it composes the cached project walk with this matcher.
"""

from __future__ import annotations

import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Tuple

from .base import PROJECT_ROOT


@lru_cache(maxsize=4)
def load_gitignore_patterns(root: str | None = None) -> Tuple[str, ...]:
    """Load non-comment, non-blank, non-negated patterns from ``<root>/.gitignore``.

    Returns a tuple (immutable, hashable for ``lru_cache``). Pass ``root``
    as a string so the cache key is plainly hashable; defaults to
    :data:`PROJECT_ROOT` when omitted.

    Negation (``!``) and ``**`` globstar are intentionally not supported —
    the repo's ``.gitignore`` does not use them, and supporting either
    would require a real pathspec implementation. If a future
    ``.gitignore`` adds them, extend this helper rather than duplicating
    the logic in callers.
    """
    base = Path(root) if root else PROJECT_ROOT
    gitignore = base / ".gitignore"
    if not gitignore.is_file():
        return ()
    patterns: list[str] = []
    for raw in gitignore.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return tuple(patterns)


def is_path_gitignored(rel_path: str, patterns: Iterable[str]) -> bool:
    """Return True iff ``rel_path`` (POSIX-style, repo-root-relative) is
    matched by any of ``patterns``.

    Supports the shapes the repo's ``.gitignore`` actually uses:

    * Bare-basename patterns (no slash): match any path component via
      ``fnmatch``.
    * Path-qualified patterns (with slash): match from the repo root via
      ``fnmatch``, plus ``prefix/*`` shorthand and bare-prefix directory
      matching.
    * Trailing ``/`` (directory-only): treated as the stripped pattern
      because we only test against file paths.

    Behaviour intentionally diverges from real git ``pathspec``: ``*``
    here matches across ``/`` (``fnmatch`` semantics). If you need full
    fidelity, use a dedicated pathspec library.
    """
    parts = rel_path.split("/")
    for raw in patterns:
        pattern = raw.lstrip("/").rstrip("/")
        if not pattern:
            continue
        if "/" in pattern:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if pattern.endswith("/*"):
                prefix = pattern[:-2]
                if rel_path.startswith(prefix + "/"):
                    return True
            if rel_path.startswith(pattern + "/"):
                return True
        else:
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
    return False


def _reset() -> None:
    """Test-only helper: clear the cached gitignore patterns.

    Named ``_reset`` for parity with the per-domain reset helpers in
    sibling modules; ``utils.cache._reset_cache_for_tests`` orchestrates
    calls to all of them.
    """
    load_gitignore_patterns.cache_clear()
