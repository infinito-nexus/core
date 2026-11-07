from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.recover import stage


class RemoveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stage = Path(tempfile.mkdtemp(prefix="infinito-recover-test-"))
        self.read_only = self.stage / "tree" / "secrets"
        self.read_only.mkdir(parents=True)
        (self.read_only / "key.pem").write_text("x", encoding="utf-8")
        self.read_only.chmod(0o555)

    def tearDown(self) -> None:
        if self.read_only.exists():
            self.read_only.chmod(0o700)
        shutil.rmtree(self.stage, ignore_errors=True)

    def test_a_read_only_directory_rsync_kept_is_removed_too(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            stage.remove(self.stage)
        self.assertFalse(self.stage.exists())
        self.assertEqual(stderr.getvalue(), "")

    def test_a_stage_that_stays_is_named_in_a_warning(self):
        stderr = io.StringIO()
        missing = self.stage / "gone"
        with contextlib.redirect_stderr(stderr):
            stage.remove(missing)
        self.assertIn(f"the stage {missing} was not removed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
