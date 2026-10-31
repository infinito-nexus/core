from __future__ import annotations

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
    def test_only_stale_engines_are_downloaded(self):
        _touch(self.root / "grype" / "6" / "vulnerability.db", 60)
        with (
            mock.patch.object(database, "LOCK_FILE", self.root / "lock"),
            mock.patch.object(database, "fetch_databases", return_value=[]) as fetch,
        ):
            database.refresh(
                self.root, ["trivy", "grype"], lambda argv: None, lambda u, d: None
            )
        self.assertEqual(fetch.call_args.args[2], ["trivy"])

    def test_fresh_databases_download_nothing(self):
        _touch(self.root / "grype" / "6" / "vulnerability.db", 60)
        with (
            mock.patch.object(database, "LOCK_FILE", self.root / "lock"),
            mock.patch.object(database, "fetch_databases") as fetch,
        ):
            errors = database.refresh(
                self.root, ["grype"], lambda argv: None, lambda u, d: None
            )
        self.assertEqual(errors, [])
        fetch.assert_not_called()


if __name__ == "__main__":
    main()
