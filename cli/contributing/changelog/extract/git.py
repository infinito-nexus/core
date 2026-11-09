"""The git reads of the extractor, each one ``git`` call run in the repository."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

RELEASE_TAG = "v[0-9]*.[0-9]*.[0-9]*"


def run(repo: Path, *args: str) -> str:
    """Return the standard output of one git command.

    Args:
        repo: The repository the command runs in.
        args: The git subcommand and its arguments.

    Raises:
        subprocess.CalledProcessError: The command failed.
    """
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def show(repo: Path, ref: str, path: str) -> str | None:
    """Return a file's text at a ref, or ``None`` when it is absent there.

    Args:
        repo: The repository.
        ref: The commit, tag or branch.
        path: The repository-relative path.
    """
    try:
        return run(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def last_tag(repo: Path, head: str) -> str:
    """Return the newest ``vX.Y.Z`` tag before ``head``.

    Args:
        repo: The repository.
        head: The target ref; a tag on it is the release itself, not the base.
    """
    return run(
        repo, "describe", "--tags", "--abbrev=0", "--match", RELEASE_TAG, f"{head}^"
    ).strip()


def changes(
    repo: Path, base: str, head: str, pathspecs: tuple[str, ...]
) -> list[tuple[str, str, str]]:
    """Return the net file changes between two refs, renames detected.

    Args:
        repo: The repository.
        base: The base ref.
        head: The target ref.
        pathspecs: The git pathspecs the diff is limited to.

    Returns:
        ``(status letter, path at base, path at head)`` per changed file.
    """
    output = run(repo, "diff", "--name-status", "-M", base, head, "--", *pathspecs)
    rows = []
    for line in output.splitlines():
        status, *paths = line.split("\t")
        rows.append((status[0], paths[0], paths[-1]))
    return rows
