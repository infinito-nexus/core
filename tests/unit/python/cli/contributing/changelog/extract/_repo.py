"""A throwaway git repository for the extractor tests."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

AUTHOR = ("Ada Author", "ada@example.invalid")
_ENV = {
    **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class FixtureRepo:
    """A repository in ``root`` with signing off and a fixed identity.

    Args:
        root: An empty directory.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str, author: tuple[str, str] = AUTHOR) -> str:
        """Run git in the repository.

        Args:
            args: The git subcommand and its arguments.
            author: The ``(name, email)`` the commit is authored and
                committed as.
        """
        name, email = author
        env = {
            **_ENV,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def write(self, path: str, text: str) -> None:
        """Write a file below the repository root.

        Args:
            path: The repository-relative path.
            text: The file content.
        """
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message: str, author: tuple[str, str] = AUTHOR) -> None:
        """Stage everything and commit it.

        Args:
            message: The commit message, trailers included.
            author: The ``(name, email)`` of the commit.
        """
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message, author=author)

    def tag(self, name: str) -> None:
        """Tag the current commit.

        Args:
            name: The tag name.
        """
        self.git("tag", name)
