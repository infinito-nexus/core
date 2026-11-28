from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text

from ._script_shims import (
    COMMIT,
    ScriptRunner,
    deploy_env,
    host_env,
    workspace_login,
)
from ._semaphore_fake import SCRIPTS_DIR

LIB = SCRIPTS_DIR / "lib.sh"
UNKNOWN = "f" * 40
ANCESTRY = re.compile(r"\tif ! git merge-base --is-ancestor [^\n]*\n[^\n]*\n\tfi\n")
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}

MALFORMED = (
    ("", "INVENTORY_COMMIT is missing"),
    (COMMIT[:39], "INVENTORY_COMMIT is malformed"),
    (COMMIT + COMMIT[:24], "INVENTORY_COMMIT is malformed"),
    (COMMIT.upper(), "INVENTORY_COMMIT is malformed"),
    ("HEAD", "INVENTORY_COMMIT is malformed"),
    ("main", "INVENTORY_COMMIT is malformed"),
    ("-" + COMMIT[1:], "INVENTORY_COMMIT is malformed"),
)
SCRIPTS = (
    ("deploy.sh", ("devices.yml",), deploy_env),
    ("host.sh", ("update",), host_env),
    ("host.sh", ("backup",), host_env),
)


class InventoryCommitTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.addCleanup(self.runner.cleanup)
        self.login = workspace_login(self)[0]

    def test_each_inventory_script_refuses_a_malformed_commit_before_git(self):
        for script, args, env in SCRIPTS:
            for value, message in MALFORMED:
                with self.subTest(f"{script} {args[0]} {value!r}"):
                    run = self.runner.run(
                        script, {**self.login, **env(INVENTORY_COMMIT=value)}, args
                    )
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(message, run.stderr)
                    self.assertEqual(self.runner.git_calls(), [])

    def test_a_well_formed_commit_is_checked_against_main_and_checked_out(self):
        for script, args, env in SCRIPTS:
            with self.subTest(f"{script} {args[0]}"):
                run = self.runner.run(script, {**self.login, **env()}, args)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(
                    self.runner.git_calls(),
                    [
                        [
                            "merge-base",
                            "--is-ancestor",
                            COMMIT,
                            "refs/remotes/origin/main",
                        ],
                        ["checkout", "--quiet", "--detach", COMMIT],
                        ["rev-parse", "HEAD"],
                    ],
                )


class ScratchRepository:
    def __init__(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.path = Path(self.scratch.name)
        self.git("init", "--quiet", "--initial-branch=main")
        self.main = self.commit("main")
        self.git("update-ref", "refs/remotes/origin/main", self.main)
        self.git("checkout", "--quiet", "-b", "other")
        self.other = self.commit("other")

    def cleanup(self):
        self.scratch.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            env={**os.environ, **GIT_ENV},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def commit(self, name):
        (self.path / name).write_text(name, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", name)
        return self.git("rev-parse", "HEAD")

    def check(self, lib, commit):
        """Args:
            lib: the path of the ``lib.sh`` to source.
            commit: the ``INVENTORY_COMMIT`` of the task.

        Returns:
            The completed ``checkout_commit`` run in the checkout.
        """
        return subprocess.run(
            [
                "bash",
                "-euo",
                "pipefail",
                "-c",
                'source "$1"; checkout_commit',
                "bash",
                str(lib),
            ],
            cwd=self.path,
            env={
                **os.environ,
                **GIT_ENV,
                "SCRIPT": "deploy.sh",
                "INVENTORY_COMMIT": commit,
            },
            capture_output=True,
            text=True,
            check=False,
        )


def commit_findings(lib, repository):
    """Args:
        lib: the path of the ``lib.sh`` to source.
        repository: a fresh :class:`ScratchRepository`.

    Returns:
        One finding per case ``checkout_commit`` gets wrong: a commit on
        ``main`` runs and leaves ``HEAD`` there, a commit only on another
        branch and an unknown id are refused as not on ``main``.
    """
    findings = []
    run = repository.check(lib, repository.main)
    if run.returncode != 0 or repository.git("rev-parse", "HEAD") != repository.main:
        findings.append("a commit on main does not run at that commit")
    for case, commit in (
        ("a commit of another branch", repository.other),
        ("an unknown id", UNKNOWN),
    ):
        run = repository.check(lib, commit)
        if run.returncode != 2 or "is not on main" not in run.stderr:
            findings.append(f"{case} is not refused")
    return findings


class CommitOnMainTests(unittest.TestCase):
    def setUp(self):
        self.repository = ScratchRepository()
        self.addCleanup(self.repository.cleanup)

    def test_the_commit_must_lie_on_main(self):
        self.assertNotEqual(
            self.repository.git("rev-parse", "HEAD"), self.repository.main
        )
        self.assertEqual(commit_findings(LIB, self.repository), [])

    def test_negative_control_without_the_ancestry_check_another_branch_runs(self):
        text = read_text(str(LIB))
        planted = ANCESTRY.sub("", text)
        self.assertNotEqual(planted, text)
        path = self.repository.path.parent / f"{self.repository.path.name}-lib.sh"
        path.write_text(planted, encoding="utf-8")
        self.addCleanup(path.unlink)
        self.assertEqual(
            commit_findings(path, self.repository),
            [
                "a commit of another branch is not refused",
                "an unknown id is not refused",
            ],
        )


if __name__ == "__main__":
    unittest.main()
