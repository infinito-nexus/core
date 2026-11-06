"""The paths one iteration changed, and their content on both sides of the diff.

The base defaults to the merge base of ``origin/main`` and ``HEAD``, the point
``scripts/meta/resolve/diff/affected_roles.sh`` diffs from, but nothing is
fetched: the plan reads the refs as they are, so two runs on the same tree
answer the same. Rename detection is off, so a moved file lists both its old
and its new path and neither side of the move is lost.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import NamedTuple

from utils.cache.files import PROJECT_ROOT, read_text, untracked_files

MAIN = "origin/main"


class Span(NamedTuple):
    """The two sides of one diff.

    Attributes:
        base: the commit the diff starts from.
        head: the commit it ends at; empty for the working tree, so uncommitted
            and untracked edits count.
    """

    base: str
    head: str


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "safe.directory=*", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise LookupError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def _commit(ref: str) -> str:
    return _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").strip()


def resolve(base: str, head: str) -> Span:
    """Return the span of the diff, both sides resolved to commits.

    Args:
        base: a ref; empty takes the merge base of ``origin/main`` and ``HEAD``.
        head: a ref; empty takes the working tree.

    Raises:
        SystemExit: a ref does not resolve. Guessing another base would plan
            a different diff than the one asked about.
    """
    try:
        start = _commit(base) if base else _git("merge-base", MAIN, "HEAD").strip()
        end = _commit(head) if head else ""
    except LookupError as exc:
        raise SystemExit(
            f"iterate-plan: cannot resolve the diff ({exc}); pass base=<ref>"
        ) from exc
    return Span(start, end)


def _names(*args: str) -> set[str]:
    return {name for name in _git(*args).split("\0") if name}


def changed_paths(span: Span) -> list[str]:
    """Return every repository-relative path the span changes, sorted.

    Args:
        span: the diff; a working-tree head adds the untracked files that
            ``.gitignore`` does not exclude.
    """
    if span.head:
        return sorted(
            _names("diff", "--no-renames", "--name-only", "-z", span.base, span.head)
        )
    names = _names("diff", "--no-renames", "--name-only", "-z", span.base)
    names.update(untracked_files())
    return sorted(names)


def content(ref: str, path: str) -> str | None:
    """Return the text of *path* at *ref*, None where it does not exist.

    Args:
        ref: a commit; empty reads the working tree.
        path: repository-relative POSIX path.
    """
    if not ref:
        file = Path(str(PROJECT_ROOT)) / path
        if not file.is_file():
            return None
        try:
            return read_text(str(file))
        except (OSError, UnicodeDecodeError):
            return None
    try:
        return _git("show", f"{ref}:{path}")
    except LookupError:
        return None
