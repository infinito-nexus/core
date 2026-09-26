"""Unit tests for :mod:`utils.env.handlers.infinito.cache.conf`."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import conf as handler

_BLANK = {handler.SOURCE_KEY: "", handler.KEY: ""}


def _ctx(root: Path, static: dict[str, str] | None = None) -> BuildContext:
    return BuildContext(
        static=static or {},
        static_comments={handler.KEY: handler.COMMENT},
        repo_root=root,
        on_gha=False,
        on_act=False,
    )


def _apply(ctx: BuildContext) -> str:
    eb = EnvBuilder()
    handler.apply(eb, ctx)
    return eb.values[handler.KEY]


class TestPrimaryCheckout(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.primary = self.root / "primary"
        self.primary.mkdir()
        self._git("init", "-q", "-b", "main", cwd=self.primary)
        self._git("config", "user.email", "t@t", cwd=self.primary)
        self._git("config", "user.name", "t", cwd=self.primary)
        (self.primary / "seed").write_text("seed\n")
        self._git("add", "seed", cwd=self.primary)
        self._git("commit", "-qm", "seed", cwd=self.primary)

    def _git(self, *args: str, cwd: Path) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def test_the_primary_checkout_resolves_to_itself(self) -> None:
        self.assertEqual(handler.primary_checkout(self.primary), self.primary)

    def test_a_worktree_resolves_to_the_primary_checkout(self) -> None:
        linked = self.root / "linked"
        self._git("worktree", "add", "-q", str(linked), "-b", "side", cwd=self.primary)

        self.assertEqual(handler.primary_checkout(linked), self.primary)

    def test_a_directory_outside_git_falls_back_to_itself(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()

        self.assertEqual(handler.primary_checkout(outside), outside)

    def test_a_root_git_cannot_be_run_in_falls_back_to_itself(self) -> None:
        missing = self.root / "gone"

        self.assertEqual(handler.primary_checkout(missing), missing)


class TestApply(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_the_default_follows_the_primary_checkout(self) -> None:
        with patch.object(handler, "primary_checkout", return_value=Path("/primary")):
            self.assertEqual(
                _apply(_ctx(self.root)), str(Path("/primary") / handler.RELATIVE)
            )

    @patch.dict(os.environ, {**_BLANK, handler.SOURCE_KEY: "worktree"}, clear=False)
    def test_the_environment_can_pin_the_worktree(self) -> None:
        self.assertEqual(_apply(_ctx(self.root)), str(self.root / handler.RELATIVE))

    @patch.dict(os.environ, _BLANK, clear=False)
    def test_a_static_entry_can_pin_the_worktree(self) -> None:
        ctx = _ctx(self.root, {handler.SOURCE_KEY: "Worktree"})

        self.assertEqual(_apply(ctx), str(self.root / handler.RELATIVE))

    @patch.dict(os.environ, {**_BLANK, handler.SOURCE_KEY: "primary"}, clear=False)
    def test_an_unknown_source_keeps_the_primary_checkout(self) -> None:
        with patch.object(handler, "primary_checkout", return_value=Path("/primary")):
            self.assertEqual(
                _apply(_ctx(self.root)), str(Path("/primary") / handler.RELATIVE)
            )


if __name__ == "__main__":
    unittest.main()
