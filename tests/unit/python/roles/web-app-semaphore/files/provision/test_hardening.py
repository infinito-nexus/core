from __future__ import annotations

import errno
import os
import shutil
import stat
import unittest
import unittest.mock as mock
from pathlib import Path

from ._fake_provision import harness_directory, load

hardening = load("provision.hardening")
CHMOD = Path.chmod


class TestHarden(unittest.TestCase):
    def test_the_spawner_closes_tmp_the_root_and_the_shared_directories(self):
        base = harness_directory()
        self.addCleanup(shutil.rmtree, base)
        tmp, root, shared = base / "tmp", base / "root", base / "shm"
        for path in (tmp, root, shared):
            path.mkdir()
            path.chmod(0o1777)
        listener = hardening.harden(
            os.getuid(), os.getgid(), root, tmp, (shared,), base
        )
        listener.close()
        modes = {
            path.name: stat.S_IMODE(path.stat().st_mode) for path in (tmp, root, shared)
        }
        name = hardening.sandbox.SOCKET_NAME
        socket_mode = stat.S_IMODE((tmp / name).stat().st_mode)
        self.assertEqual(modes, {"tmp": 0o700, "root": 0o711, "shm": 0o775})
        self.assertEqual(socket_mode, 0o600)


class TestCloseOpen(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)
        self.tmp, self.root = self.base / "tmp", self.base / "root"
        self.shared = self.base / "var" / "tmp"
        self.lock = self.base / "run" / "lock"
        self.kept = self.base / "usr" / "share"
        for path in (self.tmp, self.root, self.shared, self.lock, self.kept):
            path.mkdir(parents=True)
        for path in (self.tmp, self.shared, self.lock):
            path.chmod(0o1777)
        self.kept.chmod(0o755)

    def close_open(self):
        return hardening.close_open(self.base, self.root, self.tmp, [self.shared])

    def open_left(self):
        return hardening.world_writable(self.base, (self.root, self.tmp))

    def test_a_planted_world_writable_directory_is_closed(self):
        self.assertEqual(sorted(self.close_open()), sorted([self.lock, self.shared]))
        self.assertEqual(self.open_left(), [])
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o775)
        self.assertEqual(stat.S_IMODE(self.kept.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.tmp.stat().st_mode), 0o1777)

    def test_a_directory_that_cannot_be_closed_refuses_the_start(self):
        lock = self.lock

        def refusing(path, mode):
            if path == lock:
                raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(path))
            return CHMOD(path, mode)

        with (
            mock.patch.object(Path, "chmod", refusing),
            self.assertRaisesRegex(SystemExit, f"{lock} stays writable for every uid"),
        ):
            self.close_open()

    def test_negative_control_without_the_walk_the_planted_directory_stays_writable(
        self,
    ):
        with mock.patch.object(hardening, "world_writable", return_value=[]):
            self.assertEqual(self.close_open(), [self.shared])
        self.assertEqual(self.open_left(), [self.lock])

    def hidden_findings(self):
        """Returns:
        A finding when the spawner starts while a world-writable directory
        lies below one every uid may pass but the walk cannot list.
        """
        parent = self.base / "srv"
        below = parent / "drop"
        below.mkdir(parents=True)
        below.chmod(0o777)
        parent.chmod(0o311)
        self.addCleanup(parent.chmod, 0o755)
        try:
            self.close_open()
        except SystemExit:
            return []
        if below.stat().st_mode & stat.S_IWOTH:
            return [f"{below} stays writable for every uid"]
        return []

    def test_a_passable_directory_the_walk_cannot_list_refuses_the_start(self):
        self.assertEqual(self.hidden_findings(), [])

    def test_negative_control_without_the_check_a_hidden_directory_stays_open(self):
        with mock.patch.object(hardening, "hidden", return_value=[]):
            findings = self.hidden_findings()
        self.assertEqual(
            findings, [f"{self.base / 'srv' / 'drop'} stays writable for every uid"]
        )


if __name__ == "__main__":
    unittest.main()
