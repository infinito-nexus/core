"""Unit tests for :mod:`utils.env.handlers.infinito.domain`."""

from __future__ import annotations

import io
import os
import subprocess
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import domain as handler

_GIT = [
    "git",
    "-c",
    "user.name=t",
    "-c",
    "user.email=t@t",
    "-c",
    "commit.gpgSign=false",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run([*_GIT, "-C", str(repo), *args], check=True, capture_output=True)


def _repository(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return repo


def _worktree(repo: Path, branch: str) -> Path:
    path = repo.parent / "worktree"
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def _apply(
    repo_root: Path, *, on_gha: bool = False, on_act: bool = False
) -> str | None:
    ctx = BuildContext(
        static={},
        static_comments={},
        repo_root=repo_root,
        on_gha=on_gha,
        on_act=on_act,
    )
    eb = EnvBuilder()
    eb.set("INFINITO_DNS_DOMAIN", "infinito.test")
    handler.apply(eb, ctx)
    return eb.values.get(handler.KEY)


class TestDomain(unittest.TestCase):
    def test_primary_checkout_is_main(self) -> None:
        with TemporaryDirectory() as td:
            self.assertEqual(_apply(_repository(Path(td))), "main.infinito.test")

    def test_directory_without_git_is_main(self) -> None:
        with TemporaryDirectory() as td:
            self.assertEqual(_apply(Path(td)), "main.infinito.test")

    def test_worktree_is_its_normalised_branch(self) -> None:
        with TemporaryDirectory() as td:
            worktree = _worktree(_repository(Path(td)), "Feature/Store_I18n.v2")

            self.assertEqual(_apply(worktree), "feature-store_i18n-v2.infinito.test")

    def test_worktree_with_unreachable_git_directory_keeps_the_default(
        self,
    ) -> None:
        with TemporaryDirectory() as td:
            checkout = Path(td)
            (checkout / ".git").write_text(
                "gitdir: /host/only/.git/worktrees/x\n", encoding="utf-8"
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                self.assertIsNone(_apply(checkout))

        self.assertIn("not reachable", stderr.getvalue())

    def test_branch_too_long_for_a_dns_label_fails(self) -> None:
        with TemporaryDirectory() as td:
            worktree = _worktree(_repository(Path(td)), "a" * 64)

            with self.assertRaises(SystemExit):
                _apply(worktree)

    def test_stale_caller_value_is_replaced_but_ci_runs_keep_the_default(
        self,
    ) -> None:
        with TemporaryDirectory() as td:
            worktree = _worktree(_repository(Path(td)), "feature/x")

            with patch.dict(os.environ, {handler.KEY: "infinito.test"}):
                self.assertEqual(_apply(worktree), "feature-x.infinito.test")
            self.assertIsNone(_apply(worktree, on_gha=True))
            self.assertIsNone(_apply(worktree, on_act=True))


if __name__ == "__main__":
    unittest.main()
