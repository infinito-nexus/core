from __future__ import annotations

import http.client
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, mock

from utils.security import database
from utils.security.pipeline import pipeline

P = pipeline()


def _touch(path: Path, age: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("db", encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


class _Root(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestOsvUrl(TestCase):
    def test_an_ecosystem_with_a_space_is_quoted(self):
        self.assertEqual(
            database.osv_url("Red Hat"),
            "https://osv-vulnerabilities.storage.googleapis.com/Red%20Hat/all.zip",
        )


class TestFetchDatabases(_Root):
    def _fetch(self, engines, returncode):
        downloads = []
        calls = []

        def runner(argv):
            calls.append(list(argv))
            return SimpleNamespace(
                returncode=returncode, stdout="", stderr="no network"
            )

        def fetch(url, destination):
            downloads.append(url)
            destination.write_bytes(b"zip")

        errors = database.fetch_databases(P, self.root, engines, runner, fetch)
        return errors, calls, downloads

    def test_osv_lands_in_the_layout_the_scanner_reads(self):
        errors, _calls, downloads = self._fetch(["osv"], 0)
        self.assertEqual(errors, [])
        self.assertTrue(
            (self.root / "osv" / "osv-scalibr" / "Ubuntu" / "all.zip").is_file()
        )
        self.assertEqual(len(downloads), len(database.osv_zips(P, self.root)))

    def test_a_failed_download_is_reported(self):
        errors, calls, _downloads = self._fetch(["grype"], 1)
        self.assertTrue(errors[0].startswith("grype database: exited 1"))
        self.assertIn(["db", "update"], [call[-2:] for call in calls])

    def test_a_download_that_leaves_no_database_is_reported(self):
        errors, _calls, _downloads = self._fetch(["trivy"], 0)
        self.assertTrue(any("provided database" in error for error in errors))

    def test_an_interrupted_osv_download_leaves_no_zip_and_is_reported(self):
        def fetch(url, destination):
            destination.write_bytes(b"trunc")
            raise TimeoutError("timed out")

        errors = database.fetch_databases(P, self.root, ["osv"], None, fetch)
        ubuntu = self.root / "osv" / "osv-scalibr" / "Ubuntu"
        self.assertIn("osv Ubuntu: timed out", errors)
        self.assertEqual(list(ubuntu.iterdir()), [])

    def test_a_truncated_chunked_osv_download_leaves_no_zip_and_is_reported(self):
        def fetch(url, destination):
            destination.write_bytes(b"trunc")
            raise http.client.IncompleteRead(b"trunc", 1024)

        errors = database.fetch_databases(P, self.root, ["osv"], None, fetch)
        ubuntu = self.root / "osv" / "osv-scalibr" / "Ubuntu"
        self.assertTrue(
            any(error.startswith("osv Ubuntu: IncompleteRead") for error in errors)
        )
        self.assertEqual(list(ubuntu.iterdir()), [])


class TestStale(_Root):
    def test_a_missing_database_is_stale(self):
        self.assertTrue(database.stale(P, self.root, "grype", time.time()))

    def test_a_database_of_today_is_fresh(self):
        _touch(self.root / "grype" / "6" / "vulnerability.db", 3600)
        self.assertFalse(database.stale(P, self.root, "grype", time.time()))

    def test_a_database_older_than_a_day_is_stale(self):
        _touch(
            self.root / "grype" / "6" / "vulnerability.db",
            database.MAX_AGE_SECONDS + 60,
        )
        self.assertTrue(database.stale(P, self.root, "grype", time.time()))

    def test_osv_is_stale_while_one_ecosystem_is_missing(self):
        zips = database.osv_zips(P, self.root)
        for path in zips[1:]:
            _touch(path, 60)
        self.assertTrue(database.stale(P, self.root, "osv", time.time()))


class TestRefresh(_Root):
    def _refresh(self, engines, fetched=()):
        with mock.patch.object(
            database, "fetch_databases", return_value=list(fetched)
        ) as fetch:
            errors = database.refresh(
                self.root, engines, lambda argv: None, lambda u, d: None
            )
        return errors, fetch

    def test_only_stale_engines_are_downloaded(self):
        _touch(self.root / "grype" / "6" / "vulnerability.db", 60)
        _errors, fetch = self._refresh(["trivy", "grype"])
        self.assertEqual(fetch.call_args.args[2], ["trivy"])

    def test_fresh_databases_download_nothing(self):
        _touch(self.root / "grype" / "6" / "vulnerability.db", 60)
        errors, fetch = self._refresh(["grype"])
        self.assertEqual(errors, [])
        fetch.assert_not_called()

    def test_the_lock_lives_in_the_shared_directory(self):
        self._refresh(["grype"])
        self.assertTrue((self.root / database.LOCK_NAME).is_file())

    def test_a_missing_shared_directory_is_created(self):
        self.root = self.root / "vulnerability-db"
        self._refresh(["grype"])
        self.assertTrue(self.root.is_dir())

    def test_a_failed_download_is_returned(self):
        errors, _fetch = self._refresh(["grype"], ["grype database: exited 1"])
        self.assertEqual(errors, ["grype database: exited 1"])


class TestHandOver(_Root):
    def _outside(self) -> Path:
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        return Path(other.name)

    def _owned(self, euid=0, swap_at=None, swap=None):
        """Run hand_over with a recording chown and return what it re-owned.

        Args:
            euid: the effective uid hand_over sees.
            swap_at: the entry name whose re-owning triggers *swap*.
            swap: called at *swap_at* to change the tree mid-walk.

        Returns:
            ``(real path, (uid, gid))`` per call, every path component but the
            last resolved.
        """
        owned = []

        def chown(name, uid, gid, *, dir_fd=None, follow_symlinks=True):
            self.assertIs(follow_symlinks, False)
            if dir_fd is None:
                parent = Path(os.path.realpath(Path(name).parent))
            else:
                parent = Path(f"/proc/self/fd/{dir_fd}").readlink()
            owned.append((parent / Path(name).name, (uid, gid)))
            if swap and Path(name).name == swap_at:
                swap()

        with (
            mock.patch.object(database.os, "geteuid", return_value=euid),
            mock.patch.object(database.os, "chown", side_effect=chown),
        ):
            database.hand_over(self.root, [self.root / "osv"])
        return owned

    def _real(self, *parts: str) -> Path:
        return Path(os.path.realpath(self.root)).joinpath(*parts)

    def test_a_root_refresh_gives_every_file_to_the_directory_owner(self):
        _touch(self.root / "osv" / "osv-scalibr" / "Ubuntu" / "all.zip", 60)
        owner = self.root.stat()
        owner = (owner.st_uid, owner.st_gid)
        self.assertEqual(
            set(self._owned()),
            {
                (self._real("osv"), owner),
                (self._real("osv", "osv-scalibr"), owner),
                (self._real("osv", "osv-scalibr", "Ubuntu"), owner),
                (self._real("osv", "osv-scalibr", "Ubuntu", "all.zip"), owner),
            },
        )

    def test_a_planted_symlink_is_changed_itself_never_its_target(self):
        outside = self._outside()
        (outside / "passwd").write_text("x", encoding="utf-8")
        (self.root / "osv").mkdir(parents=True)
        (self.root / "osv" / "link").symlink_to(outside / "passwd")
        paths = [path for path, _owner in self._owned()]
        self.assertIn(self._real("osv", "link"), paths)
        self.assertNotIn(Path(os.path.realpath(outside)) / "passwd", paths)

    def test_a_listed_path_that_is_a_symlink_is_skipped(self):
        outside = self._outside()
        _touch(outside / "secret", 60)
        (self.root / "osv").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self._owned(), [])

    def test_a_directory_swapped_for_a_symlink_mid_walk_is_not_followed(self):
        outside = self._outside()
        _touch(outside / "e" / "f", 60)
        _touch(self.root / "osv" / "d" / "e" / "f", 60)

        def swap():
            (self.root / "osv" / "d").rename(self.root / "osv" / "d2")
            (self.root / "osv" / "d").symlink_to(outside, target_is_directory=True)

        owned = self._owned(swap_at="e", swap=swap)
        escaped = Path(os.path.realpath(outside))
        self.assertTrue(owned)
        for path, _owner in owned:
            self.assertFalse(path.is_relative_to(escaped), path)

    def test_an_unprivileged_refresh_changes_no_owner(self):
        _touch(self.root / "osv" / "osv-scalibr" / "Ubuntu" / "all.zip", 60)
        self.assertEqual(self._owned(euid=1000), [])

    def test_a_root_refresh_that_wrote_no_database_hands_over_the_lock(self):
        with (
            mock.patch.object(database.os, "geteuid", return_value=0),
            mock.patch.object(database.os, "chown") as chown,
            mock.patch.object(database, "fetch_databases", return_value=[]),
        ):
            database.refresh(self.root, ["grype"], lambda argv: None, lambda u, d: None)
        self.assertEqual(
            [Path(call.args[0]) for call in chown.call_args_list],
            [self.root / database.LOCK_NAME],
        )


if __name__ == "__main__":
    main()
