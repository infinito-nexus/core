"""Repository scans see a file before it is added, whichever runner lists the files."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from tests.integration.infrastructure.compose import test_no_raw_docker as raw_docker
from tests.lint.filesystem.python import test_python_shebangs as shebangs
from tests.lint.repository import test_comments_valid as comments
from tests.lint.repository.documentation import test_todo_transparency as todo
from utils.cache import files as files_module

TRACKED = "tracked.py"
UNTRACKED = "new.py"
FAILED = subprocess.CalledProcessError(128, "git")


class _ListingFixture:
    """Mixin with a project root holding one tracked and one untracked file.

    Combined with ``unittest.TestCase`` on each concrete class so the
    test-discovery lint sees the ``TestCase`` base directly.
    """

    def setUp(self) -> None:
        super().setUp()
        files_module._reset()
        self.addCleanup(files_module._reset)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in (TRACKED, UNTRACKED):
            (self.root / name).write_text("", encoding="utf-8")
        for module in (files_module, comments):
            patcher = mock.patch.object(module, "PROJECT_ROOT", self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, tracked: bytes | Exception, untracked: bytes | Exception):
        def run(args, **_kwargs):
            listing = untracked if "--others" in args else tracked
            if isinstance(listing, Exception):
                raise listing
            return SimpleNamespace(stdout=listing)

        return mock.patch.object(files_module.subprocess, "run", side_effect=run)


class TestScansListUntrackedFiles(_ListingFixture, unittest.TestCase):
    def test_every_scan_lists_a_file_that_is_not_added_yet(self):
        scans = {
            "test_python_shebangs": lambda: shebangs.TestPythonShebangs._tracked_files(
                SimpleNamespace(repo_root=self.root)
            ),
            "test_todo_transparency": lambda: todo.tracked_files(self.root),
            "test_no_raw_docker": lambda: raw_docker.git_ls_files(self.root),
        }
        for name, scan in scans.items():
            with (
                self.subTest(scan=name),
                self.git(f"{TRACKED}\0".encode(), f"{UNTRACKED}\0".encode()),
            ):
                files_module._reset()
                self.assertIn(self.root / UNTRACKED, scan())


class TestCommentScanKeepsEachListing(_ListingFixture, unittest.TestCase):
    def test_failing_tracked_listing_keeps_the_untracked_files(self):
        with self.git(FAILED, f"{UNTRACKED}\0".encode()):
            self.assertEqual([self.root / UNTRACKED], comments._all_targets())

    def test_failing_untracked_listing_keeps_the_tracked_files(self):
        with self.git(f"{TRACKED}\0".encode(), FAILED):
            self.assertEqual([self.root / TRACKED], comments._all_targets())


if __name__ == "__main__":
    unittest.main()
