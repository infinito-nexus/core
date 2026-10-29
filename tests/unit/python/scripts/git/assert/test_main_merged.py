from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "git" / "assert" / "main_merged.sh"
MAIN_COMMIT_ENV = "INFINITO_MAIN_COMMIT"  # nocheck: git maintainer tooling knob, not a deployment env key


class MainMergedFixture:
    """A bare ``origin`` whose ``main`` moved on after ``head`` branched off it.

    Args:
        tmp: directory that holds the bare remote and its two clones.
    """

    def __init__(self, tmp: str) -> None:
        root = Path(tmp)
        inherited = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("GIT_", "INFINITO_"))
        }
        self.env = {
            **inherited,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        origin = root / "origin.git"
        maintainer = root / "maintainer"
        self.head = root / "head"
        self.git(root, "init", "--bare", "-b", "main", str(origin))
        self.git(root, "init", "-b", "main", str(maintainer))
        self.git(maintainer, "remote", "add", "origin", str(origin))
        self.base = self.commit(maintainer, "base")
        self.git(maintainer, "push", "origin", "main")
        self.git(root, "clone", str(origin), str(self.head))
        self.git(self.head, "switch", "-c", "feature")
        self.commit(self.head, "feature")
        self.main_tip = self.commit(maintainer, "main moved on")
        self.git(maintainer, "push", "origin", "main")

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self, repo: Path, message: str) -> str:
        self.git(repo, "commit", "--allow-empty", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def merge_main(self) -> None:
        self.git(self.head, "pull", "--no-rebase", "--no-edit", "origin", "main")

    def run_script(self, main_commit: str | None) -> subprocess.CompletedProcess:
        """Run the script in ``head``.

        Args:
            main_commit: value of the main-commit override; ``None`` leaves it unset.
        """
        env = dict(self.env)
        if main_commit is not None:
            env[MAIN_COMMIT_ENV] = main_commit
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.head,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class TestMainMergedPinnedCommit(unittest.TestCase):
    def test_contained_commit_passes_after_main_moved_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = MainMergedFixture(tmp)
            result = fixture.run_script(fixture.base)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"origin/main@{fixture.base} is fully merged", result.stderr)

    def test_commit_missing_from_head_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = MainMergedFixture(tmp)
            result = fixture.run_script(fixture.main_tip)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                f"origin/main@{fixture.main_tip} has 1 commit(s) not merged into HEAD",
                result.stderr,
            )

    def test_empty_commit_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = MainMergedFixture(tmp)
            result = fixture.run_script("")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("must be a full commit SHA", result.stderr)


class TestMainMergedLiveTip(unittest.TestCase):
    def test_live_tip_missing_from_head_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = MainMergedFixture(tmp)
            result = fixture.run_script(None)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "origin/main has 1 commit(s) not merged into HEAD", result.stderr
            )

    def test_merged_live_tip_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = MainMergedFixture(tmp)
            fixture.merge_main()
            result = fixture.run_script(None)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("origin/main is fully merged into HEAD", result.stderr)


if __name__ == "__main__":
    unittest.main()
