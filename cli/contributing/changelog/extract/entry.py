"""Insert a release entry into a scratch copy of ``CHANGELOG.md`` and lint it."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CONFIG = ".markdownlint-cli2.jsonc"
_ENTRY_HEADER = re.compile(r"^## \[", re.MULTILINE)


def insert(changelog: str, entry: str) -> str:
    """Return the changelog with the entry before its newest release.

    Args:
        changelog: The ``CHANGELOG.md`` text.
        entry: The entry, opening with its ``## [X.Y.Z] - YYYY-MM-DD`` line;
            a leading ``# Changelog`` heading is dropped.

    Raises:
        ValueError: The entry has no release header.
    """
    start = _ENTRY_HEADER.search(entry)
    if start is None:
        raise ValueError("the entry has no '## [X.Y.Z] - YYYY-MM-DD' header")
    body = entry[start.start() :].strip() + "\n\n"
    first = _ENTRY_HEADER.search(changelog)
    if first is None:
        return changelog.rstrip() + "\n\n" + body.rstrip() + "\n"
    return changelog[: first.start()] + body + changelog[first.start() :]


def linter() -> list[str]:
    """Return the markdownlint-cli2 command already on this host.

    Raises:
        FileNotFoundError: Neither ``markdownlint-cli2`` nor ``npx`` is
            installed; nothing is installed here.
    """
    if binary := shutil.which("markdownlint-cli2"):
        return [binary]
    if npx := shutil.which("npx"):
        return [npx, "--no-install", "markdownlint-cli2"]
    raise FileNotFoundError("markdownlint-cli2 is not installed: run make install-lint")


def lint(scratch: Path, config: Path) -> subprocess.CompletedProcess:
    """Lint ``CHANGELOG.md`` in a scratch directory with the repository rules.

    Args:
        scratch: A directory holding only the scratch ``CHANGELOG.md``; the
            repository configuration is copied next to it so its globs reach
            no other file.
        config: The repository's ``.markdownlint-cli2.jsonc``.
    """
    shutil.copyfile(config, scratch / CONFIG)
    return subprocess.run(
        [*linter(), "CHANGELOG.md"],
        cwd=scratch,
        capture_output=True,
        text=True,
        check=False,
    )
