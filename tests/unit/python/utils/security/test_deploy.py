from __future__ import annotations

import contextlib
import io
import random
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from utils.security import deploy
from utils.security.engine import ENGINE_ENV, ROLE, databases_for


class TestInventoryOverrides(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.refreshed = []

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self, engine):
        return mock.patch.dict(
            "os.environ",
            {
                ENGINE_ENV: engine,
                deploy.HOST_PATH_ENV: str(self.root),
                deploy.TARGET_DIR_ENV: "/opt/vulnerability-db",
            },
        )

    def _refresher(self, errors):
        def refresher(root, engines):
            self.refreshed.append((root, engines))
            return errors

        return refresher

    def _overrides(self, engine, errors=()):
        with self._env(engine), contextlib.redirect_stdout(io.StringIO()):
            return deploy.inventory_overrides(
                random.Random(4),  # noqa: S311 - seeded draw, not crypto
                self._refresher(list(errors)),
            )

    def _runtime(self, overrides):
        return overrides[ROLE]["services"]["runtime"]

    def test_a_local_deploy_draws_one_engine_behind_syft(self):
        engines = self._runtime(self._overrides(""))["engines"]
        self.assertEqual((len(engines), engines[0]), (2, "syft"))

    def test_a_local_deploy_refreshes_the_shared_databases_it_reads(self):
        engine = self._runtime(self._overrides(""))["engines"][1]
        self.assertEqual(self.refreshed, [(self.root, databases_for(engine))])

    def test_the_stack_reads_the_read_only_mount(self):
        runtime = self._runtime(self._overrides(""))
        self.assertEqual(
            (runtime["database_dir"], runtime["db_update"]),
            ("/opt/vulnerability-db", False),
        )

    def test_a_failed_refresh_fails_the_deploy(self):
        with self.assertRaisesRegex(SystemExit, "no network"):
            self._overrides("", errors=["grype database: no network"])

    def test_a_pinned_engine_never_downloads(self):
        for name in ("trivy", "grype"):
            (self.root / name).mkdir()
            (self.root / name / "db").write_text("x", encoding="utf-8")
        self.assertEqual(
            self._runtime(self._overrides("trivy"))["engines"], ["syft", "trivy"]
        )
        self.assertEqual(self.refreshed, [])

    def test_a_pinned_engine_without_its_databases_fails(self):
        (self.root / "grype").mkdir()
        (self.root / "grype" / "db").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "no osv database"):
            self._overrides("osv")


if __name__ == "__main__":
    main()
