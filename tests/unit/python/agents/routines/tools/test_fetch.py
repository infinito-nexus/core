"""Unit test: the routine fetch updates the remote branch although a tag the
remote moved clobbers the local one, where a tag-importing fetch fails, and
the push routine's trigger step runs that fetch."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agents.routines import push_trigger_pull
from agents.routines.tools.fetch import fetch_argv

GIT_ENV = {
    "GIT_AUTHOR_NAME": "routine",
    "GIT_AUTHOR_EMAIL": "routine@example.invalid",
    "GIT_COMMITTER_NAME": "routine",
    "GIT_COMMITTER_EMAIL": "routine@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=check,
    )


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-q", "--allow-empty", "--no-gpg-sign", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


class TestClobberedTagFetch(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.upstream = Path(tmp.name) / "upstream"
        self.fork = Path(tmp.name) / "fork"
        _git(Path(tmp.name), "init", "-q", "-b", "main", str(self.upstream))
        _commit(self.upstream, "first")
        _git(self.upstream, "tag", "v1")
        _git(Path(tmp.name), "clone", "-q", str(self.upstream), str(self.fork))
        _git(self.fork, "config", "remote.origin.tagOpt", "--tags")
        self.head = _commit(self.upstream, "second")
        _git(self.upstream, "tag", "-f", "v1")

    def _origin_main(self) -> str:
        return _git(self.fork, "rev-parse", "refs/remotes/origin/main").stdout.strip()

    def test_routine_fetch_succeeds_on_a_clobbered_tag(self) -> None:
        result = subprocess.run(
            fetch_argv("origin", "main"),
            cwd=self.fork,
            env={**os.environ, **GIT_ENV},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual((result.returncode, self._origin_main()), (0, self.head))

    def test_negative_control_a_tag_importing_fetch_fails(self) -> None:
        result = _git(self.fork, "fetch", "origin", "main", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("would clobber existing tag", result.stderr)

    def test_trigger_step_runs_the_routine_fetch(self) -> None:
        steps = {step.id: step for step in push_trigger_pull.STEPS}
        state = steps["trigger"].fn({})
        self.assertEqual(state["fetch"], " ".join(fetch_argv("origin", "main")))


if __name__ == "__main__":
    unittest.main()
