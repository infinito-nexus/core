from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import signal
import subprocess
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

from tests.utils.unprivileged import unprivileged

FAKES = importlib.import_module("..provision._fake_provision", __package__)
harness_directory = FAKES.harness_directory
probe = FAKES.load("sandbox.probe")
WALK = probe.written
OWN = probe.MARKER_PREFIX + "own"
OTHER = probe.MARKER_PREFIX + "other"
HOLD = "import time; time.sleep(60)"


class TestSandboxProbe(unittest.TestCase):
    def setUp(self):
        self.root = harness_directory()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.token = self.root / "runner.token"
        self.token.write_bytes(b"x")
        self.work, self.tmp, self.other = (
            self.root / name for name in ("semaphore", "tmp", "task")
        )
        for directory in (self.work, self.tmp, self.other):
            directory.mkdir()
        for patcher in (
            mock.patch.object(probe, "SETTLE_SECONDS", 0),
            mock.patch.object(probe, "written", return_value=[]),
            mock.patch.object(probe, "ipc_segment", return_value=-1),
            mock.patch.dict(os.environ, {probe.MARKER: OWN}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_probe(self, *paths):
        report = probe.probe(*map(str, paths), [str(self.other)])
        self.addCleanup(self.end, report["child"])
        return report

    @staticmethod
    def end(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)

    def test_a_probe_outside_any_sandbox_reports_what_it_reaches(self):
        other = subprocess.Popen(
            [sys.executable, "-c", HOLD], env={**os.environ, probe.MARKER: OTHER}
        )
        self.addCleanup(self.end, other.pid)
        report = self.run_probe(self.token, self.work, self.tmp)
        for read in (
            "token",
            "marker",
            f"closed {self.work}",
            f"closed {self.tmp}",
            f"task {self.other}",
        ):
            self.assertIn(read, report["reads"])
        self.assertTrue(probe.alive(report["child"]))
        self.assertTrue(report["child_mem"])

    def test_negative_control_paths_it_cannot_reach_stay_unreported(self):
        gone = self.root / "gone"
        report = self.run_probe(gone / "token", gone / "work", gone / "tmp")
        self.assertEqual(
            [read for read in report["reads"] if str(self.root) in read],
            [f"task {self.other}"],
        )
        self.assertNotIn("token", report["reads"])

    def test_the_walk_reports_writable_directories_outside_its_own(self):
        own, foreign = self.root / "own", self.root / "foreign"
        own.mkdir()
        foreign.mkdir()
        writes = WALK([own, self.work, self.tmp, self.other], self.root)
        expected = [f"writes {self.root}", f"writes {foreign}"]
        self.assertEqual(sorted(writes), sorted(expected))
        self.assertEqual(list(foreign.iterdir()), [])


class TestProbeClasses(unittest.TestCase):
    def setUp(self):
        self.root = harness_directory()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        child = subprocess.Popen([sys.executable, "-c", HOLD])
        self.addCleanup(TestSandboxProbe.end, child.pid)
        self.entry = probe.PROC / str(child.pid)

    def test_the_mem_probe_reads_a_mapped_address(self):
        self.assertTrue(probe.mem_readable(self.entry))

    def test_negative_control_a_read_at_offset_zero_reads_nothing(self):
        self.assertFalse(probe.readable(self.entry / "mem"))

    def test_the_walk_reaches_a_writable_directory_it_cannot_list(self):
        hidden = self.root / "hidden"
        hidden.mkdir()
        hidden.chmod(0o333)
        self.addCleanup(hidden.chmod, 0o700)
        self.assertIn(f"writes {hidden}", WALK([], self.root))

    @unprivileged
    def test_negative_control_a_walk_of_listed_directories_misses_it(self):
        hidden = self.root / "hidden"
        hidden.mkdir()
        hidden.chmod(0o333)
        self.addCleanup(hidden.chmod, 0o700)
        if os.access(hidden, os.R_OK):
            self.skipTest("this process lists a 0333 directory, so no walk misses it")
        walk = os.walk(self.root)  # nocheck: project-walk
        listed = [Path(directory) for directory, _names, _files in walk]
        self.assertEqual(listed, [self.root])
        self.assertIn(hidden, probe.sandbox.walked(self.root, ()))


if __name__ == "__main__":
    unittest.main()
