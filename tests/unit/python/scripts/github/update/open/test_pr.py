from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "update" / "open" / "pr.sh"
PINNED_FILE = "pin.txt"
GH_STUB = """#!/usr/bin/env bash
if [[ "$1 $2" == "pr list" ]]; then
	printf '7\\t%s\\n' "${GH_STUB_BRANCH}"
fi
"""


class UpdatePrFixture:
    """A throwaway repo with one pending pin bump and a ``gh`` that lists one open PR.

    Args:
        tmp: directory that holds the repo and the ``gh`` stub.
    """

    def __init__(self, tmp: str) -> None:
        self.repo = Path(tmp) / "repo"
        self.repo.mkdir()
        stub_dir = Path(tmp) / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "gh"
        stub.write_text(GH_STUB)
        stub.chmod(0o755)
        inherited = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env = {
            **inherited,
            "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ALLOW_PROTOCOL": "file",
            "GH_TOKEN": "unused",
            "UPDATE_BRANCH_PREFIX": "update/pins",
            "UPDATE_BRANCH_SUFFIX": "20260101",
            "UPDATE_BASE_BRANCH": "main",
            "UPDATE_COMMIT_MESSAGE": "update: bump",
            "UPDATE_PR_TITLE": "update: bump",
            "UPDATE_PR_BODY": "bump",
        }
        self.git("init", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        (self.repo / PINNED_FILE).write_text("1.0\n")
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "init",
        )
        (self.repo / PINNED_FILE).write_text("1.1\n")

    def git(self, *args: str, stdin: str | None = None) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def fingerprint(self) -> str:
        blob = self.git("hash-object", PINNED_FILE)
        return self.git("hash-object", "--stdin", stdin=f"{blob}\t{PINNED_FILE}\n")

    def open_pr(self, open_branch: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.repo,
            env={**self.env, "GH_STUB_BRANCH": open_branch},
            capture_output=True,
            text=True,
            check=False,
        )


class TestUpdatePrDedupe(unittest.TestCase):
    def test_edited_branch_of_the_same_proposal_is_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = UpdatePrFixture(tmp)
            branch = f"update/pins-20251231-{fixture.fingerprint()[:7]}"
            result = fixture.open_pr(branch)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Open PR #7 already carries this exact change", result.stdout)
            self.assertNotIn("Pushing change to branch", result.stdout)

    def test_branch_of_another_proposal_is_not_a_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = UpdatePrFixture(tmp)
            result = fixture.open_pr("update/pins-20251231-0000000")
            self.assertNotIn("already carries this exact change", result.stdout)
            self.assertIn(
                f"Pushing change to branch update/pins-20260101-{fixture.fingerprint()[:7]}",
                result.stdout,
            )


if __name__ == "__main__":
    unittest.main()
