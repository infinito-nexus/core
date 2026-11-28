from __future__ import annotations

import contextlib
import fcntl
import io
import os
import stat
import tempfile
import threading
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "svc-net-platform-monitoring"
    / "files"
    / "python"
    / "digest_line.py"
)
OWN = f"target {'a' * 64}"
RENEWED = f"target {'c' * 64}"
OTHER = f"targetx {'b' * 64}"


def _load():
    spec = spec_from_file_location("digest_line_under_test", SCRIPT)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


digest_line = _load()


def held(path):
    """Args:
    path: a digest file the test wrote through ``converge``.

    Returns:
        Its text, read fresh since ``converge`` rewrites it within the test.
    """
    return path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read tempfile rewritten in-test


class ConvergeTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name, "federate.sha256")

    def test_a_first_line_creates_the_file_once(self):
        self.assertTrue(digest_line.converge(self.path, "target", OWN))
        self.assertFalse(digest_line.converge(self.path, "target", OWN))
        self.assertEqual(held(self.path), f"{OWN}\n")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), digest_line.MODE)

    def test_a_deploy_rewrites_only_its_own_line(self):
        digest_line.converge(self.path, "target", OWN)
        digest_line.converge(self.path, "targetx", OTHER)
        self.assertTrue(digest_line.converge(self.path, "target", RENEWED))
        self.assertEqual(held(self.path), f"{OTHER}\n{RENEWED}\n")

    def test_a_drop_removes_its_line_and_the_last_one_the_file(self):
        digest_line.converge(self.path, "target", OWN)
        digest_line.converge(self.path, "targetx", OTHER)
        self.assertTrue(digest_line.converge(self.path, "target", None))
        self.assertEqual(held(self.path), f"{OTHER}\n")
        self.assertTrue(digest_line.converge(self.path, "targetx", None))
        self.assertFalse(self.path.exists())
        self.assertFalse(digest_line.converge(self.path, "targetx", None))

    def test_negative_control_a_line_of_another_host_is_refused(self):
        with self.assertRaisesRegex(ValueError, "another host"):
            digest_line.converge(self.path, "target", OTHER)
        self.assertFalse(self.path.exists())

    def test_negative_control_a_symbolic_link_is_refused(self):
        target = self.path.with_name("elsewhere")
        target.write_text(f"{OTHER}\n", encoding="utf-8")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            digest_line.converge(self.path, "target", OWN)
        self.assertEqual(held(target), f"{OTHER}\n")

    def test_the_edit_waits_for_the_lock_a_release_holds(self):
        lock = os.open(
            f"{self.path}{digest_line.LOCK_SUFFIX}", os.O_RDWR | os.O_CREAT, 0o600
        )
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        edit = threading.Thread(
            target=digest_line.converge, args=(self.path, "target", OWN)
        )
        edit.start()
        edit.join(timeout=0.5)
        self.assertTrue(edit.is_alive())
        self.assertFalse(self.path.exists())
        fcntl.flock(lock, fcntl.LOCK_UN)
        edit.join(timeout=5)
        self.assertFalse(edit.is_alive())
        self.assertEqual(held(self.path), f"{OWN}\n")


class MainTests(unittest.TestCase):
    def test_the_command_line_reports_the_change(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = str(Path(scratch, "federate.sha256"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(digest_line.main([path, "target", OWN]), 0)
                self.assertEqual(digest_line.main([path, "target", OWN]), 0)
                self.assertEqual(digest_line.main([path, "target"]), 0)
            self.assertEqual(out.getvalue(), "changed\nunchanged\nchanged\n")

    def test_negative_control_a_wrong_command_line_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(digest_line.main(["only-a-file"]), 2)


if __name__ == "__main__":
    unittest.main()
