"""Unit tests for cli.administration.recover.full discovery + pull."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.recover import full, paths, remote
from cli.administration.recover import stage as recover_stage
from utils.recovery.layout import MANIFEST_SCHEMA
from utils.storage.nfs import get_export_base


class PlanTest(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        base = root / "HASH"
        (base / "backup-nfs-to-local" / "20260101000000" / "files").mkdir(parents=True)
        (
            base / "backup-docker-to-local" / "20260101000000" / "pg_data" / "files"
        ).mkdir(parents=True)
        (base / "backup-docker-to-local" / "20260101000000" / "redis" / "files").mkdir(
            parents=True
        )
        (base / "backup-secrets-to-local" / "20260101000000" / "files").mkdir(
            parents=True
        )

    def test_plan_order_and_volume_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            steps, _unreadable = full.plan(root)
            types = [t for t, _ in steps]
            self.assertEqual(types, ["nfs", "volume", "volume", "secrets"])
            self.assertTrue(
                steps[0][1].endswith("backup-nfs-to-local/20260101000000/files")
            )
            self.assertTrue(any(s.endswith("pg_data/files") for _, s in steps))
            self.assertTrue(any(s.endswith("redis/files") for _, s in steps))

    def test_a_dump_compressed_or_plain_adds_the_database_step(self):
        for name in ("zammad.backup.sql.gz", "zammad.backup.sql"):
            with self.subTest(dump=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._tree(root)
                generation = root / "HASH/backup-docker-to-local/20260101000000"
                (generation / "pg_data/sql").mkdir()
                (generation / "pg_data/sql" / name).write_bytes(b"")
                steps, _unreadable = full.plan(root)
                self.assertEqual(
                    [t for t, _ in steps],
                    ["nfs", "volume", "volume", "database", "secrets"],
                )

    def test_negative_control_a_file_that_is_no_dump_adds_no_database_step(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            generation = root / "HASH/backup-docker-to-local/20260101000000"
            (generation / "pg_data/sql").mkdir()
            (generation / "pg_data/sql/zammad.backup.sql.tmp").write_bytes(b"")
            steps, _unreadable = full.plan(root)
            self.assertNotIn("database", [t for t, _ in steps])

    def test_plan_picks_newest_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "HASH" / "backup-nfs-to-local"
            (repo / "20260101000000" / "files").mkdir(parents=True)
            (repo / "20260709120000" / "files").mkdir(parents=True)
            steps, _unreadable = full.plan(root)
            self.assertEqual(len(steps), 1)
            self.assertIn("20260709120000", steps[0][1])

    def test_plan_empty_root(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(full.plan(Path(td)), ([], []))

    def test_a_colon_generation_is_reported_and_not_planned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "HASH" / "backup-nfs-to-local"
            (repo / "20260101000000" / "etc").mkdir(parents=True)
            (repo / "20260101000000:" / "files").mkdir(parents=True)
            steps, unreadable = full.plan(root)
        self.assertEqual(steps, [])
        self.assertEqual(len(unreadable), 1)
        self.assertIn("backup-nfs-to-local", unreadable[0])

    def test_an_option_shaped_volume_is_reported_and_the_rest_planned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._tree(root)
            generation = root / "HASH/backup-docker-to-local/20260101000000"
            (generation / "--no-safety-backup" / "files").mkdir(parents=True)
            steps, unreadable = full.plan(root)
        volumes = [source for rtype, source in steps if rtype == "volume"]
        self.assertEqual(len(volumes), 2)
        self.assertNotIn("--no-safety-backup", " ".join(volumes))
        self.assertEqual(len(unreadable), 1)
        self.assertIn("--no-safety-backup", unreadable[0])

    def test_a_files_dir_linked_outside_is_reported_and_not_planned(self):
        with (
            tempfile.TemporaryDirectory() as td,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(td)
            generation = root / "HASH" / "backup-nfs-to-local" / "20260101000000"
            generation.mkdir(parents=True)
            (generation / "files").symlink_to(outside, target_is_directory=True)
            steps, unreadable = full.plan(root)
        self.assertEqual(steps, [])
        self.assertEqual(len(unreadable), 1)
        self.assertIn("leads outside", unreadable[0])

    def test_a_volume_linked_outside_is_reported_and_the_rest_planned(self):
        with (
            tempfile.TemporaryDirectory() as td,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(td)
            self._tree(root)
            generation = root / "HASH/backup-docker-to-local/20260101000000"
            (generation / "escape").mkdir()
            (generation / "escape" / "files").symlink_to(
                outside, target_is_directory=True
            )
            steps, unreadable = full.plan(root)
        volumes = [source for rtype, source in steps if rtype == "volume"]
        self.assertEqual(len(volumes), 2)
        self.assertNotIn("escape", " ".join(volumes))
        self.assertEqual(len(unreadable), 1)
        self.assertIn("leads outside", unreadable[0])


class NfsStepTargetTest(unittest.TestCase):
    def test_nfs_generation_files_restore_onto_the_export_base(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = root / "HASH" / "backup-nfs-to-local" / "20260101000000" / "files"
            files.mkdir(parents=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                full._recover_under(
                    root, "localhost", preview=True, service_backup=False
                )
        line = next(
            entry
            for entry in out.getvalue().splitlines()
            if entry.startswith("# full nfs")
        )
        argv = shlex.split(line.split(": ", 1)[1])
        self.assertEqual(
            argv[2:], [str(files), get_export_base(), "--no-safety-backup"]
        )


class DeviceDetectTest(unittest.TestCase):
    def test_file_is_device(self):
        with tempfile.NamedTemporaryFile() as tf:
            self.assertTrue(full._is_device(tf.name))
            self.assertTrue(full._is_device(f"{tf.name}:usb:/tmp/r"))

    def test_directory_is_not_device(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(full._is_device(td))

    def test_restore_root_from_absolute_segment(self):
        self.assertEqual(full._device_restore_root("/dev/sdb1:usb:/tmp/r"), "/tmp/r")

    def test_restore_root_defaults_to_backup_root(self):
        self.assertEqual(full._device_restore_root("/dev/sdb1:usb"), paths.BACKUP_ROOT)


class PullCmdTest(unittest.TestCase):
    def test_bare_host_uses_standard_root(self):
        self.assertEqual(
            full._pull_cmd("user@srchost", "/stage/tree"),
            [
                "rsync",
                "-aHAX",
                f"user@srchost:{paths.BACKUP_ROOT}/",
                "/stage/tree/",
            ],
        )

    def test_host_with_explicit_path(self):
        self.assertEqual(
            full._pull_cmd("host:/custom/root", "/stage/tree"),
            ["rsync", "-aHAX", "host:/custom/root/", "/stage/tree/"],
        )


class PullStageTest(unittest.TestCase):
    def _run(self, *, pull_rc: int = 0, recover: object = 0) -> tuple[int, dict]:
        seen: dict = {"recovered": []}

        def fake_run(cmd, check):
            if cmd[0] == "rsync":
                destination = Path(cmd[-1])
                stage = destination.parent
                if not stage.name.startswith(full.PULL_STAGE_PREFIX):
                    raise AssertionError(f"pull lands outside a private stage: {cmd}")
                seen["stage"] = stage
                seen["destination"] = destination
                seen["stage_mode"] = stat.S_IMODE(stage.stat().st_mode)
                seen["stage_owner"] = stage.stat().st_uid
                seen["stage_entries"] = list(stage.iterdir())
                if pull_rc == 0:
                    (
                        destination
                        / "HASH"
                        / "backup-nfs-to-local"
                        / "20260101000000"
                        / "files"
                    ).mkdir(parents=True)
                return subprocess.CompletedProcess(cmd, pull_rc)
            if "stage" not in seen:
                raise AssertionError(f"ran before the pull: {cmd}")
            seen["recovered"].append(cmd)
            seen["stage_during_recover"] = seen["stage"].is_dir()
            if isinstance(recover, BaseException):
                raise recover
            return subprocess.CompletedProcess(cmd, recover)

        with (
            patch.object(full.subprocess, "run", side_effect=fake_run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            returncode = full.run(
                "user@srchost", "localhost", preview=False, service_backup=False
            )
        return returncode, seen

    def test_the_stage_is_fresh_owner_only_and_unpredictable(self):
        _returncode, seen = self._run()
        stage = seen["stage"]
        self.assertEqual(seen["stage_mode"], 0o700)
        self.assertEqual(seen["stage_owner"], os.getuid())
        self.assertEqual(seen["stage_entries"], [])
        self.assertEqual(stage.parent, Path(tempfile.gettempdir()))
        self.assertTrue(stage.name.startswith(full.PULL_STAGE_PREFIX))
        self.assertGreater(len(stage.name), len(full.PULL_STAGE_PREFIX))

    def test_the_tree_lands_below_the_stage_not_in_it(self):
        _returncode, seen = self._run()
        self.assertEqual(seen["destination"], seen["stage"] / recover_stage.TREE)

    def test_the_recovery_reads_from_the_pulled_tree(self):
        returncode, seen = self._run()
        self.assertEqual(returncode, 0)
        self.assertTrue(seen["stage_during_recover"])
        self.assertEqual(len(seen["recovered"]), 1)
        self.assertIn(str(seen["destination"]), seen["recovered"][0][2])

    def test_the_stage_is_gone_after_the_run(self):
        _returncode, seen = self._run()
        self.assertFalse(seen["stage"].exists())

    def test_the_stage_is_gone_when_the_pull_fails(self):
        returncode, seen = self._run(pull_rc=23)
        self.assertEqual(returncode, 2)
        self.assertEqual(seen["recovered"], [])
        self.assertFalse(seen["stage"].exists())

    def test_the_stage_is_gone_when_a_recovery_fails(self):
        returncode, seen = self._run(recover=1)
        self.assertEqual(returncode, 1)
        self.assertFalse(seen["stage"].exists())

    def test_the_stage_is_gone_when_the_recovery_raises(self):
        stages: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def tracked(*args, **kwargs):
            directory = real_mkdtemp(*args, **kwargs)
            stages.append(Path(directory))
            return directory

        with (
            patch.object(recover_stage.tempfile, "mkdtemp", side_effect=tracked),
            self.assertRaises(KeyboardInterrupt),
        ):
            self._run(recover=KeyboardInterrupt())
        self.assertEqual(len(stages), 1)
        self.assertFalse(stages[0].exists())

    def test_a_failed_removal_keeps_the_exit_code_and_names_the_stage(self):
        for recover_rc in (0, 1):
            stderr = io.StringIO()
            with (
                self.subTest(recover_rc=recover_rc),
                patch.object(
                    recover_stage.shutil, "rmtree", side_effect=OSError("busy")
                ),
                contextlib.redirect_stderr(stderr),
            ):
                returncode, seen = self._run(recover=recover_rc)
            shutil.rmtree(seen["stage"])
            self.assertEqual(returncode, recover_rc)
            self.assertIn(
                f"the stage {seen['stage']} was not removed", stderr.getvalue()
            )

    def test_a_preview_creates_no_stage_and_runs_nothing(self):
        out = io.StringIO()
        with (
            patch.object(recover_stage.tempfile, "mkdtemp", side_effect=AssertionError),
            patch.object(full.subprocess, "run", side_effect=AssertionError),
            contextlib.redirect_stdout(out),
        ):
            returncode = full.run(
                "user@srchost", "localhost", preview=True, service_backup=False
            )
        self.assertEqual(returncode, 0)
        self.assertIn("rsync -aHAX", out.getvalue())


class RemoteDeviceStageTest(unittest.TestCase):
    REMOTE_DIR = "/tmp/tmp.Remote12345"

    def _run(self, *, device_rc: int = 0) -> tuple[int, dict]:
        seen: dict = {"ssh": [], "recovered": []}

        def fake_run(cmd, check, **kwargs):
            if cmd[0] == "ssh":
                seen["ssh"].append(cmd)
                if cmd[2:] == ["mktemp", "-d"]:
                    return subprocess.CompletedProcess(cmd, 0, f"{self.REMOTE_DIR}\n")
                return subprocess.CompletedProcess(cmd, 0 if "rm" in cmd else device_rc)
            if cmd[0] == "rsync":
                destination = Path(cmd[-1])
                local_stage = destination.parent
                if not local_stage.name.startswith(remote.STAGE_PREFIX):
                    raise AssertionError(f"pull lands outside a private stage: {cmd}")
                seen["local_stage"] = local_stage
                seen["stage_mode"] = stat.S_IMODE(local_stage.stat().st_mode)
                seen["pull"] = cmd
                (
                    destination
                    / "HASH"
                    / "backup-secrets-to-local"
                    / "20260101000000"
                    / "files"
                ).mkdir(parents=True)
                return subprocess.CompletedProcess(cmd, 0)
            seen["recovered"].append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with (
            patch.object(full.subprocess, "run", side_effect=fake_run),
            patch.object(full.sys, "stdin", io.StringIO()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            returncode = full.run(
                "root@srchost:/dev/sdb1:usb",
                "localhost",
                preview=False,
                service_backup=False,
            )
        return returncode, seen

    def test_the_host_recovers_into_its_own_mktemp_dir(self):
        _returncode, seen = self._run()
        recover_cmd = seen["ssh"][1][2]
        self.assertIn(f"{self.REMOTE_DIR}/{recover_stage.TREE}", recover_cmd)
        self.assertNotIn("infinito-recover-remote-root", recover_cmd)
        self.assertEqual(
            seen["pull"][2], f"root@srchost:{self.REMOTE_DIR}/{recover_stage.TREE}/"
        )

    def test_the_local_stage_is_owner_only_and_gone_after_the_run(self):
        returncode, seen = self._run()
        self.assertEqual(returncode, 0)
        self.assertEqual(seen["stage_mode"], 0o700)
        self.assertEqual(len(seen["recovered"]), 1)
        self.assertFalse(seen["local_stage"].exists())

    def test_the_host_dir_is_removed_after_success_and_failure(self):
        for device_rc in (0, 1):
            with self.subTest(device_rc=device_rc):
                returncode, seen = self._run(device_rc=device_rc)
                self.assertEqual(returncode, device_rc)
                self.assertEqual(
                    seen["ssh"][-1],
                    ["ssh", "root@srchost", "rm", "-rf", "--", self.REMOTE_DIR],
                )


if __name__ == "__main__":
    unittest.main()


class TestUnreadableManifest(unittest.TestCase):
    """One corrupt manifest must not block the repos that are intact."""

    def _root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        bad = root / "hash" / "backup-nfs-to-local" / "20260101000000"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text(
            '{"schema": 99, "layout": {}, "volumes": {}}', encoding="utf-8"
        )
        (
            root / "hash" / "backup-docker-to-local" / "20260101000000" / "v" / "files"
        ).mkdir(parents=True)
        return root

    def test_the_intact_repo_is_still_planned(self) -> None:
        steps, _unreadable = full.plan(self._root())
        self.assertEqual([rtype for rtype, _src in steps], ["volume"])

    def test_the_skipped_repo_is_named(self) -> None:
        _steps, unreadable = full.plan(self._root())
        self.assertEqual(len(unreadable), 1)
        self.assertIn("backup-nfs-to-local", unreadable[0])


class TestEscapingLayout(unittest.TestCase):
    def test_an_absolute_files_dir_is_reported_and_not_planned(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root_dir,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(root_dir)
            bad = root / "hash" / "backup-secrets-to-local" / "20260101000000"
            bad.mkdir(parents=True)
            (bad / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": MANIFEST_SCHEMA,
                        "layout": {
                            "files_dir": outside,
                            "sql_dir": "sql",
                            "dump_suffix": ".backup.sql.gz",
                            "cluster_suffix": ".cluster.backup.sql.gz",
                        },
                        "volumes": {},
                    }
                ),
                encoding="utf-8",
            )
            steps, unreadable = full.plan(root)
        self.assertEqual(steps, [])
        self.assertEqual(len(unreadable), 1)
        self.assertIn("backup-secrets-to-local", unreadable[0])

    def test_a_layout_missing_a_name_is_reported_not_crashed(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            bad = root / "hash" / "backup-secrets-to-local" / "20260101000000"
            (bad / "files").mkdir(parents=True)
            (bad / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": MANIFEST_SCHEMA,
                        "layout": {"files_dir": "files"},
                        "volumes": {},
                    }
                ),
                encoding="utf-8",
            )
            steps, unreadable = full.plan(root)
        self.assertEqual(steps, [])
        self.assertEqual(len(unreadable), 1)
