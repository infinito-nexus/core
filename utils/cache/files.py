"""Process-level cached filesystem helpers for project-tree scans.

Many integration/lint tests and CLI tools walk the whole repo and read every
matching file. Doing that N times per process is wasteful — the tree doesn't
change during a run. These helpers walk the tree once per process and memoise
both the path list and file contents, so every caller after the first one pays
near-zero cost.

Usage:

    from utils.cache.files import iter_project_files, read_text

    for path in iter_project_files(extensions=(".yml", ".yml.j2"), exclude_tests=True):
        content = read_text(path)
        ...

`PROJECT_ROOT` is the repo root derived from this file's location.

Gitignore-filtered iteration
----------------------------

The matcher itself lives in :mod:`utils.cache.gitignore` (single SPOT for
``.gitignore`` parsing and matching). :func:`iter_non_ignored_files`
here composes the cached project walk with that matcher and is the
recommended helper for lint tests that want the "files git would track"
view without subprocessing.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.roles.custom import is_custom_path

from . import PROJECT_ROOT
from .gitignore import is_path_gitignored, load_gitignore_patterns

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

_DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "vendor",
    }
)

_ROOT_SKIP_DIRS: frozenset[str] = frozenset({"build"})


@lru_cache(maxsize=1)
def _local_exclude_dirs() -> frozenset[str]:
    """Directory names from ``.git/info/exclude`` (git's local-only ignore).

    Untracked local tooling output listed there is by definition not part of
    the project, so project-tree scans must not descend into it. Only plain
    single-component directory entries are honored — file patterns and globs
    stay with git.
    """
    exclude = Path(str(PROJECT_ROOT)) / ".git" / "info" / "exclude"
    names: set[str] = set()
    try:
        lines = exclude.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        token = line.strip("/")
        if token and not any(c in token for c in "/*?["):
            names.add(token)
    return frozenset(names)


@lru_cache(maxsize=4)
def _all_project_files(root_str: str) -> tuple[str, ...]:
    """One-shot filesystem walk from *root_str*.

    Returns absolute paths as a tuple (immutable → safe to cache).
    Pruned at walk-time by `_DEFAULT_SKIP_DIRS` plus git's local exclude
    file, since those dirs are never relevant for any project-tree test and
    descending into them is pure waste.
    """
    skip_dirs = _DEFAULT_SKIP_DIRS | _local_exclude_dirs()
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_str, topdown=True):
        skip = skip_dirs
        if dirpath == root_str:
            skip = skip | _ROOT_SKIP_DIRS
        dirnames[:] = [d for d in dirnames if d not in skip]
        paths.extend(str(Path(dirpath) / fn) for fn in filenames)
    return tuple(paths)


def iter_project_files(
    *,
    extensions: Iterable[str] | None = None,
    exclude_tests: bool = False,
    exclude_dirs: Iterable[str] | None = None,
) -> Iterator[str]:
    """Yield absolute paths of project files matching the filter.

    Args:
        extensions: Suffix strings (e.g. ``(".yml", ".yaml.j2")``). Matching is
            case-insensitive via plain string suffix. ``None`` yields all files.
        exclude_tests: Skip everything under ``<root>/tests/``.
        exclude_dirs: Additional top-level-or-nested directory names to skip.
            Matched by path-component containment, not by prefix. E.g.
            ``exclude_dirs=("docs",)`` skips any file whose path contains a
            ``docs`` segment.
    """
    yield from _filtered(
        _all_project_files(str(PROJECT_ROOT)),
        extensions=extensions,
        exclude_tests=exclude_tests,
        exclude_dirs=exclude_dirs,
    )


def _filtered(
    paths: Iterable[str],
    *,
    extensions: Iterable[str] | None,
    exclude_tests: bool,
    exclude_dirs: Iterable[str] | None,
) -> Iterator[str]:
    tests_prefix = str(Path(str(PROJECT_ROOT)) / "tests") + os.sep
    ext_lower = tuple(e.lower() for e in extensions) if extensions else None
    exclude_dirs_set = set(exclude_dirs) if exclude_dirs else None

    for path in paths:
        if exclude_tests and path.startswith(tests_prefix):
            continue
        if exclude_dirs_set is not None:
            rel = os.path.relpath(path, str(PROJECT_ROOT))
            if exclude_dirs_set.intersection(Path(rel).parts):
                continue
        if ext_lower is not None:
            lower = path.lower()
            if not any(lower.endswith(e) for e in ext_lower):
                continue
        yield path


READ_TEXT_CACHE_MAX_BYTES = 1 << 20


def _read(path: str) -> str:
    with Path(path).open(encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=8192)
def _read_cached(path: str) -> str:
    return _read(path)


def read_text(path: str) -> str:
    """Return the UTF-8 text content of a file; cached process-wide.

    A file larger than ``READ_TEXT_CACHE_MAX_BYTES`` on disk is read again on
    every call and never cached. The ``locale/*/LC_MESSAGES/docs.po``
    catalogs hold 1.2 GiB, which Python keeps as about 4 GiB of str, and a
    whole-tree content scan pinned that in every pytest-xdist worker that
    ran one until the 16 GiB CI runner swapped to death.

    Args:
        path: absolute path of the file to read.

    Returns:
        The decoded content of the file.

    Raises:
        OSError: the file cannot be stat'ed or read.
        UnicodeDecodeError: the file is not UTF-8; callers that scan
            arbitrary files catch it when non-UTF-8 blobs may appear.
    """
    try:
        size = Path(path).stat().st_size
    except FileNotFoundError:
        return _read_cached(path)
    if size > READ_TEXT_CACHE_MAX_BYTES:
        return _read(path)
    return _read_cached(path)


TRANSLATION_CATALOG_DIR = "locale"
TRANSLATION_CATALOG_SUFFIX = ".po"


def is_translation_catalog(rel: str) -> bool:
    """Return whether *rel* is a gettext catalog of the ``locale/`` tree.

    Args:
        rel: repository-relative POSIX path.

    Returns:
        True for ``locale/**/*.po``, which ``i18n-extract`` regenerates from
        the documentation the content scans already read at its source.
    """
    return rel.startswith(f"{TRANSLATION_CATALOG_DIR}/") and rel.endswith(
        TRANSLATION_CATALOG_SUFFIX
    )


def iter_project_files_with_content(
    *,
    extensions: Iterable[str] | None = None,
    exclude_tests: bool = False,
    exclude_dirs: Iterable[str] | None = None,
    include_catalogs: bool = False,
) -> Iterator[tuple[str, str]]:
    """Yield ``(path, content)`` for matching files; content is cached.

    Files that fail to read (permission errors, non-UTF-8) are silently
    skipped, as the callers did around ``open().read()`` before.

    Args:
        extensions: see :func:`iter_project_files`.
        exclude_tests: see :func:`iter_project_files`.
        exclude_dirs: see :func:`iter_project_files`.
        include_catalogs: also read the ``locale/**/*.po`` catalogs
            (:func:`is_translation_catalog`). They hold 1.2 GiB that
            ``read_text`` never caches, so every scan reading them re-reads
            all of it; only a scan whose rule concerns them opts in.
    """
    root_prefix = str(PROJECT_ROOT) + os.sep
    for path in iter_project_files(
        extensions=extensions,
        exclude_tests=exclude_tests,
        exclude_dirs=exclude_dirs,
    ):
        if (
            not include_catalogs
            and path.startswith(root_prefix)
            and is_translation_catalog(path[len(root_prefix) :].replace(os.sep, "/"))
        ):
            continue
        try:
            content = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        yield path, content


def iter_non_ignored_files(
    *,
    extensions: Iterable[str] | None = None,
    exclude_tests: bool = False,
    exclude_dirs: Iterable[str] | None = None,
    root: str | None = None,
) -> Iterator[str]:
    """Yield project files filtered through ``.gitignore``.

    Combines :func:`iter_project_files` with :func:`is_path_gitignored`
    so callers get the "files git would track" view without spawning a
    git subprocess. ``root`` defaults to :data:`PROJECT_ROOT`.

    A path is yielded iff it survives both the in-process skip-dir
    pruning of :func:`iter_project_files` and the ``.gitignore`` match.
    The ``.gitignore`` match runs once per process over the whole walk and
    is shared by every caller.
    """
    base = str(Path(root) if root else PROJECT_ROOT)
    yield from _filtered(
        _non_ignored_files(str(PROJECT_ROOT), base, load_gitignore_patterns(base)),
        extensions=extensions,
        exclude_tests=exclude_tests,
        exclude_dirs=exclude_dirs,
    )


@lru_cache(maxsize=4)
def _non_ignored_files(
    project_root: str, base: str, patterns: tuple[str, ...]
) -> tuple[str, ...]:
    """Paths of the project walk that ``.gitignore`` does not exclude.

    Args:
        project_root: the walked tree, part of the key so a patched
            ``PROJECT_ROOT`` never answers from another tree.
        base: directory the ``.gitignore`` paths are relative to.
        patterns: the patterns of *base*, part of the key so a reloaded
            ``.gitignore`` is matched afresh.

    Returns:
        Absolute paths in walk order; paths only, never contents.
    """
    return tuple(
        path
        for path in _all_project_files(project_root)
        if not is_path_gitignored(
            os.path.relpath(path, base).replace(os.sep, "/"), patterns
        )
    )


@lru_cache(maxsize=2)
def repository_files(*, untracked: bool = True) -> tuple[str, ...]:
    """Repository-relative POSIX paths of every file ``git ls-files`` lists.

    A tracked file deleted in the worktree is left out. Git ignores the custom
    roles an inventory pulls into ``roles/``, yet every scan checks them like
    in-tree roles, so their files are listed as well.

    Args:
        untracked: also list the untracked files ``.gitignore`` does not
            exclude, so a lint sees a new file before it is staged.

    Raises:
        OSError: git is not installed.
        subprocess.CalledProcessError: git cannot list the files.
    """
    root = str(PROJECT_ROOT)
    rels = _git_files() - _git_files("--deleted")
    if untracked:
        rels.update(untracked_files())
    rels.update(
        rel
        for path in iter_project_files()
        if is_custom_path(rel := os.path.relpath(path, root).replace(os.sep, "/"))
    )
    return tuple(sorted(rels))


LINT_SCOPE_ENV = "lint_scope"


def lint_scope() -> tuple[str, ...]:
    """Repository-relative paths ``make lint-file`` and ``make lint-role``
    narrow the scope-aware lints to, read from the ``lint_scope`` environment
    variable (space separated); empty for the whole tree."""
    raw = os.environ.get(LINT_SCOPE_ENV, "")
    return tuple(part.strip("/") for part in raw.split() if part.strip("/"))


def in_lint_scope(rel: str) -> bool:
    """Return whether a scope-aware lint checks *rel*.

    Args:
        rel: repository-relative POSIX path of a file or directory.
    """
    scope = lint_scope()
    return not scope or any(rel == s or rel.startswith(f"{s}/") for s in scope)


@lru_cache(maxsize=1)
def untracked_files() -> tuple[str, ...]:
    """Repository-relative POSIX paths of the untracked files ``.gitignore`` does not exclude.

    Raises:
        OSError: git is not installed.
        subprocess.CalledProcessError: git cannot list the files.
    """
    return tuple(sorted(_git_files("--others", "--exclude-standard")))


def _git_files(*options: str) -> set[str]:
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-files", "-z", *options],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        check=True,
    ).stdout
    return {rel for rel in out.decode("utf-8", errors="replace").split("\0") if rel}


def _reset() -> None:
    """Test-only helper: clear the project-walk and file-content caches.

    Named ``_reset`` for parity with the per-domain reset helpers in
    sibling modules; ``utils.cache.reset._reset_cache_for_tests`` orchestrates
    calls to all of them.
    """
    _all_project_files.cache_clear()
    _non_ignored_files.cache_clear()
    _local_exclude_dirs.cache_clear()
    _read_cached.cache_clear()
    repository_files.cache_clear()
    untracked_files.cache_clear()
