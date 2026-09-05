"""Contract of ``make worktree-down``.

Two promises are pinned here because both were broken. A teardown must release
the branch even when the agent sandbox pins the metadata dir as a read-only bind
mount: ``git worktree remove`` then dies with EBUSY after it has already deleted
the checkout, which used to abort the whole target with rc 255 even though the
branch was in fact free. And a status probe that fails must never be read as
"clean": on a broken ``.git`` link ``git status`` exits non-zero with empty
output, which used to satisfy the guard, tear down the compose stack, and only
then die at ``git worktree remove`` with an unexplained rc 128.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

WORKTREE_SCRIPTS = PROJECT_ROOT / "scripts" / "system" / "worktree"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}
GIT_REPO_SCOPE = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)
NEEDS_UNPRIVILEGED = "clearing the write bit does not restrain root"


class WorktreeDownFixture:
    """A throwaway repo with the worktree scripts copied in and branch ``feat``."""

    def __init__(self, tmp: str) -> None:
        self.root = Path(tmp)
        self.repo = self.root / "repo"
        self.base = self.root / "worktrees"
        self.checkout = self.base / "feat"
        # Exception: run from a pre-commit hook, git exports GIT_DIR and GIT_INDEX_FILE,
        # which would aim every command below at the real repo instead of this throwaway.
        inherited = {k: v for k, v in os.environ.items() if k not in GIT_REPO_SCOPE}
        self.env = {**inherited, **GIT_IDENTITY}

        scripts = self.repo / "scripts" / "system" / "worktree"
        scripts.parent.mkdir(parents=True)
        shutil.copytree(WORKTREE_SCRIPTS, scripts)
        self.script = scripts / "down.sh"

        self.git("init", "-b", "main")
        (self.repo / "Makefile").write_text("compose-down:\n\t@true\n")
        self.git("add", "-A")
        self.git("commit", "-m", "init")
        self.git("branch", "feat")
        self.base.mkdir()
        self.git("worktree", "add", str(self.checkout), "feat")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )

    def meta_dir(self) -> Path:
        return self.repo / ".git" / "worktrees" / "feat"

    def down(self, force: str = "false") -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.script), "feat", str(self.base), force],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def registered(self) -> bool:
        listing = self.git("worktree", "list", "--porcelain").stdout
        return str(self.checkout) in listing


class TestWorktreeDown(unittest.TestCase):
    def test_clean_worktree_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            result = fixture.down()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(fixture.checkout.exists())
            self.assertFalse(fixture.registered())

    def test_uncommitted_changes_block_the_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            (fixture.checkout / "scratch.txt").write_text("work in progress\n")
            result = fixture.down()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("uncommitted changes", result.stderr)
            self.assertTrue(fixture.checkout.exists())

    def test_force_drops_uncommitted_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            (fixture.checkout / "scratch.txt").write_text("work in progress\n")
            result = fixture.down(force="true")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(fixture.checkout.exists())

    def test_unreadable_status_refuses_instead_of_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            (fixture.checkout / ".git").write_text("gitdir: /nonexistent\n")
            result = fixture.down()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot read the git status", result.stderr)
            self.assertTrue(fixture.checkout.exists())

    @unittest.skipIf(os.geteuid() == 0, NEEDS_UNPRIVILEGED)
    def test_pinned_metadata_dir_still_releases_the_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            meta_parent = fixture.meta_dir().parent
            mode = meta_parent.stat().st_mode
            meta_parent.chmod(mode & ~stat.S_IWUSR)
            try:
                result = fixture.down()
            finally:
                meta_parent.chmod(mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(fixture.checkout.exists())
            self.assertFalse(fixture.registered())

    @unittest.skipIf(os.geteuid() == 0, NEEDS_UNPRIVILEGED)
    def test_undeletable_pointers_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            meta = fixture.meta_dir()
            mode = meta.stat().st_mode
            meta.chmod(mode & ~stat.S_IWUSR)
            try:
                result = fixture.down()
            finally:
                meta.chmod(mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("still registers branch", result.stderr)

    def test_missing_worktree_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = WorktreeDownFixture(tmp)
            shutil.rmtree(fixture.checkout)
            result = fixture.down()
            self.assertEqual(result.returncode, 1)
            self.assertIn("no worktree at", result.stderr)


if __name__ == "__main__":
    unittest.main()
