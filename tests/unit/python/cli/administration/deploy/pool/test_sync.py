from __future__ import annotations

import importlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.runner import jobs, loop

serve = importlib.import_module("cli.administration.deploy.pool.serve.__main__")
sync = importlib.import_module("cli.administration.deploy.pool.sync.__main__")

RUNNER = "runner-1"
NOW = 1_800_000_000.0


class TestSync(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(os.path.realpath(self._tmp.name))
        roots = base / "worktrees"
        self.checkout = roots / "core"
        (self.checkout / loop.ENTRY).parent.mkdir(parents=True)
        (self.checkout / loop.ENTRY).write_text("#!/bin/sh\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.checkout, check=True)
        install = base / "install" / "1"
        install.mkdir(parents=True)
        self.copy = install / "checkout"
        self.root = base / "jobs"
        self.env = {
            serve.QUEUE_KEY: str(self.root),
            serve.COMPOSE_KEY: RUNNER,
            serve.SRC_KEY: str(self.checkout),
            loop.ROOTS_KEY: str(roots),
            loop.INSTALL_KEY: str(install),
            loop.CHECKOUT_KEY: str(self.copy),
            loop.IMAGE_KEY: "toolchain",
        }
        jobs.register(self.root, RUNNER)

    def _sync(self, checkout: Path) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        code = sync.run([str(checkout)], self.env, out, err)
        return code, err.getvalue()

    def _hold(self) -> None:
        record = jobs.submit(
            self.root, str(self.checkout), "compose-deploy", [], True, NOW
        )
        jobs.claim(self.root, RUNNER, RUNNER, NOW)
        jobs.finish(self.root, record.id, 0, NOW)

    def test_a_held_runner_gets_the_edit_in_place_keeping_its_copy(self) -> None:
        self._hold()
        self.copy.mkdir()
        inode = self.copy.stat().st_ino
        (self.checkout / "edited.yml").write_text("---\n", encoding="utf-8")
        code, err = self._sync(self.checkout)
        self.assertEqual(code, 0, err)
        self.assertTrue((self.copy / "edited.yml").is_file())
        self.assertEqual(self.copy.stat().st_ino, inode)

    def test_an_idle_runner_syncs_nothing(self) -> None:
        code, err = self._sync(self.checkout)
        self.assertEqual(code, 2)
        self.assertIn("holds no job", err)
        self.assertFalse(self.copy.exists())

    def test_a_checkout_outside_the_roots_syncs_nothing(self) -> None:
        self._hold()
        code, err = self._sync(Path(self._tmp.name))
        self.assertEqual(code, 2)
        self.assertIn("is no job checkout", err)


if __name__ == "__main__":
    unittest.main()
