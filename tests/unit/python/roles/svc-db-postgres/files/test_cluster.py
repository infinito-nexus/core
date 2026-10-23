import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/svc-db-postgres/files/python/cluster.py"
    spec = importlib.util.spec_from_file_location("svc_db_postgres_cluster", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cluster = _load_module()


def make_cluster(
    root: Path, rel: str, version: str, state: str = "valid", mtime: float | None = None
) -> Path:
    path = root / rel
    (path / "global").mkdir(parents=True, exist_ok=True)
    (path / "base").mkdir(exist_ok=True)
    (path / "PG_VERSION").write_text(f"{version}\n", encoding="utf-8")
    control = path / "global" / ("pg_control" if state == "valid" else "pg_control.old")
    control.write_bytes(b"control")
    if mtime is not None:
        os.utime(control, (mtime, mtime))
    return path


class VolumeFixture:
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "_data"
        self.root.mkdir()


class TestDetect(VolumeFixture, unittest.TestCase):
    def test_empty_volume_is_fresh(self) -> None:
        self.assertEqual(cluster.detect(self.root, 18)["state"], "fresh")

    def test_cluster_in_volume_root_is_upgraded(self) -> None:
        make_cluster(self.root, "", "17")
        plan = cluster.detect(self.root, 18)
        self.assertEqual(
            (plan["state"], plan["source"], plan["major"], plan["majors"]),
            ("upgrade", "", 17, [17, 18]),
        )

    def test_source_path_of_root_cluster_is_the_volume_root(self) -> None:
        make_cluster(self.root, "", "17")
        self.assertEqual(cluster.detect(self.root, 18)["source_path"], str(self.root))

    def test_cluster_in_pgdata_wins_over_a_stray_root_pg_version(self) -> None:
        (self.root / "PG_VERSION").write_text("17\n", encoding="utf-8")
        make_cluster(self.root, "pgdata", "17")
        plan = cluster.detect(self.root, 18)
        self.assertEqual((plan["source"], plan["ignored"]), ("pgdata", []))

    def test_newest_control_file_picks_the_active_cluster(self) -> None:
        make_cluster(self.root, "", "17", mtime=1_000_000)
        make_cluster(self.root, "pgdata", "17", mtime=2_000_000)
        plan = cluster.detect(self.root, 18)
        self.assertEqual((plan["source"], plan["ignored"]), ("pgdata", [""]))

    def test_cluster_in_data_dir_is_upgraded(self) -> None:
        make_cluster(self.root, "data", "17")
        self.assertEqual(cluster.detect(self.root, 18)["source"], "data")

    def test_cluster_in_major_docker_dir_is_upgraded(self) -> None:
        make_cluster(self.root, "17/docker", "17")
        self.assertEqual(cluster.detect(self.root, 18)["source"], "17/docker")

    def test_older_major_steps_through_every_intermediate_major(self) -> None:
        make_cluster(self.root, "16/docker", "16")
        self.assertEqual(cluster.detect(self.root, 18)["majors"], [16, 17, 18])

    def test_target_cluster_in_pgdata_is_current(self) -> None:
        make_cluster(self.root, "18/docker", "18")
        plan = cluster.detect(self.root, 18)
        self.assertEqual((plan["state"], plan["leftovers"]), ("current", []))

    def test_retired_cluster_next_to_target_is_a_leftover(self) -> None:
        make_cluster(self.root, "pgdata", "17", state="retired")
        make_cluster(self.root, "18/docker", "18")
        plan = cluster.detect(self.root, 18)
        self.assertEqual((plan["state"], plan["leftovers"]), ("current", ["pgdata"]))

    def test_older_cluster_next_to_target_is_ignored(self) -> None:
        make_cluster(self.root, "", "17")
        make_cluster(self.root, "18/docker", "18")
        plan = cluster.detect(self.root, 18)
        self.assertEqual((plan["state"], plan["ignored"]), ("current", [""]))

    def test_interrupted_chain_resumes_from_the_intermediate_major(self) -> None:
        make_cluster(self.root, "16/docker", "16", state="retired")
        make_cluster(self.root, "17/docker", "17")
        plan = cluster.detect(self.root, 18)
        self.assertEqual(
            (plan["source"], plan["majors"], plan["leftovers"]),
            ("17/docker", [17, 18], ["16/docker"]),
        )

    def test_unfinished_target_directory_does_not_count(self) -> None:
        make_cluster(self.root, "pgdata", "17")
        make_cluster(self.root, "18/docker.upgrading", "18")
        self.assertEqual(cluster.detect(self.root, 18)["state"], "upgrade")

    def test_newer_major_stops_the_deploy(self) -> None:
        make_cluster(self.root, "19/docker", "19")
        with self.assertRaisesRegex(cluster.VolumeError, "newer than the pinned 18"):
            cluster.detect(self.root, 18)

    def test_target_major_outside_pgdata_stops_the_deploy(self) -> None:
        make_cluster(self.root, "", "18")
        with self.assertRaisesRegex(cluster.VolumeError, "outside the image's PGDATA"):
            cluster.detect(self.root, 18)

    def test_retired_cluster_without_successor_stops_the_deploy(self) -> None:
        make_cluster(self.root, "pgdata", "17", state="retired")
        with self.assertRaisesRegex(cluster.VolumeError, "restore the volume"):
            cluster.detect(self.root, 18)

    def test_retired_cluster_without_successor_beats_a_stale_cluster(self) -> None:
        make_cluster(self.root, "", "17", mtime=1_000_000)
        make_cluster(self.root, "pgdata", "17", state="retired")
        with self.assertRaises(cluster.VolumeError):
            cluster.detect(self.root, 18)

    def test_pre_ten_cluster_stops_the_deploy(self) -> None:
        make_cluster(self.root, "", "9.6")
        with self.assertRaisesRegex(cluster.VolumeError, "9.6"):
            cluster.detect(self.root, 18)

    def test_pg_version_without_control_file_is_not_a_cluster(self) -> None:
        (self.root / "PG_VERSION").write_text("9.6\n", encoding="utf-8")
        self.assertEqual(cluster.detect(self.root, 18)["state"], "fresh")


class TestCleanup(VolumeFixture, unittest.TestCase):
    def test_removes_retired_pgdata_and_keeps_target(self) -> None:
        make_cluster(self.root, "pgdata", "17", state="retired")
        make_cluster(self.root, "18/docker", "18")
        self.assertEqual(cluster.cleanup(self.root, 18), {"removed": ["pgdata"]})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["18"])

    def test_retired_root_cluster_keeps_foreign_directories(self) -> None:
        make_cluster(self.root, "", "17", state="retired")
        (self.root / "postgresql.conf").write_text("", encoding="utf-8")
        (self.root / "lost+found").mkdir()
        make_cluster(self.root, "18/docker", "18")
        cluster.cleanup(self.root, 18)
        self.assertEqual(
            sorted(p.name for p in self.root.iterdir()), ["18", "lost+found"]
        )

    def test_retired_intermediate_major_goes_with_its_directory(self) -> None:
        make_cluster(self.root, "16/docker", "16", state="retired")
        make_cluster(self.root, "17/docker", "17", state="retired")
        (self.root / "17" / "update_extensions.sql").write_text("", encoding="utf-8")
        make_cluster(self.root, "18/docker", "18")
        cluster.cleanup(self.root, 18)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["18"])

    def test_keeps_ignored_older_clusters(self) -> None:
        make_cluster(self.root, "", "17")
        make_cluster(self.root, "18/docker", "18")
        cluster.cleanup(self.root, 18)
        self.assertTrue((self.root / "PG_VERSION").is_file())

    def test_refuses_while_the_target_is_missing(self) -> None:
        make_cluster(self.root, "pgdata", "17")
        with self.assertRaisesRegex(cluster.VolumeError, "refusing"):
            cluster.cleanup(self.root, 18)


class TestReflink(VolumeFixture, unittest.TestCase):
    def test_supported_when_cp_clones(self) -> None:
        make_cluster(self.root, "pgdata", "17")
        done = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(cluster.subprocess, "run", return_value=done) as run:
            self.assertEqual(
                cluster.reflink_supported(self.root, "pgdata"), {"supported": True}
            )
        self.assertEqual(
            run.call_args.args[0],
            [
                "cp",
                "--reflink=always",
                str(self.root / "pgdata" / "PG_VERSION"),
                str(self.root.parent / "._data.reflink-probe"),
            ],
        )

    def test_unsupported_reports_the_reason(self) -> None:
        make_cluster(self.root, "", "17")
        failed = subprocess.CompletedProcess(
            [], 1, "", "cp: failed to clone: Operation not supported\n"
        )
        with mock.patch.object(cluster.subprocess, "run", return_value=failed):
            result = cluster.reflink_supported(self.root, "")
        self.assertEqual(
            result,
            {
                "supported": False,
                "reason": "cp: failed to clone: Operation not supported",
            },
        )

    def test_removes_the_probe(self) -> None:
        make_cluster(self.root, "", "17")
        probe = self.root.parent / "._data.reflink-probe"

        def clone(argv, **_kwargs):
            probe.write_text("17\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(cluster.subprocess, "run", side_effect=clone):
            cluster.reflink_supported(self.root, "")
        self.assertFalse(probe.exists())


class TestBackup(VolumeFixture, unittest.TestCase):
    NOW = datetime(2026, 10, 21, 18, 30, 5, tzinfo=UTC)

    def test_clones_the_volume_next_to_it(self) -> None:
        done = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(cluster.subprocess, "run", return_value=done) as run:
            result = cluster.backup(self.root, 17, self.NOW)
        dest = self.root.parent / "_data.pg17-20261021T183005Z"
        self.assertEqual(result, {"path": str(dest)})
        self.assertEqual(
            run.call_args.args[0],
            ["cp", "-a", "--reflink=always", str(self.root), str(dest)],
        )

    def test_refuses_to_overwrite_a_copy(self) -> None:
        (self.root.parent / "_data.pg17-20261021T183005Z").mkdir()
        with self.assertRaisesRegex(cluster.VolumeError, "exists already"):
            cluster.backup(self.root, 17, self.NOW)

    def test_failed_clone_stops_the_upgrade(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "", "No space left on device")
        with (
            mock.patch.object(cluster.subprocess, "run", return_value=failed),
            self.assertRaisesRegex(cluster.VolumeError, "No space left"),
        ):
            cluster.backup(self.root, 17, self.NOW)


class TestMain(VolumeFixture, unittest.TestCase):
    def test_detect_prints_the_plan_with_the_resolved_root(self) -> None:
        make_cluster(self.root, "pgdata", "17")
        link = self.root.parent / "volume"
        link.symlink_to(self.root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cluster.main(["detect", "--root", str(link), "--target", "18"])
        self.assertEqual(code, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual(
            (plan["root"], plan["source"]), (str(self.root.resolve()), "pgdata")
        )

    def test_volume_error_exits_one_with_the_message(self) -> None:
        make_cluster(self.root, "19/docker", "19")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cluster.main(["detect", "--root", str(self.root), "--target", "18"])
        self.assertEqual(code, 1)
        self.assertIn("PostgreSQL 19", err.getvalue())


if __name__ == "__main__":
    unittest.main()
