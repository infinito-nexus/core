"""Unit tests for cli.administration.recover.full discovery + pull."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.recover import full, paths


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
            steps = full.plan(root)
            types = [t for t, _ in steps]
            self.assertEqual(types, ["nfs", "volume", "volume", "secrets"])
            self.assertTrue(
                steps[0][1].endswith("backup-nfs-to-local/20260101000000/files")
            )
            self.assertTrue(any(s.endswith("pg_data/files") for _, s in steps))
            self.assertTrue(any(s.endswith("redis/files") for _, s in steps))

    def test_plan_picks_newest_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "HASH" / "backup-nfs-to-local"
            (repo / "20260101000000" / "files").mkdir(parents=True)
            (repo / "20260709120000" / "files").mkdir(parents=True)
            steps = full.plan(root)
            self.assertEqual(len(steps), 1)
            self.assertIn("20260709120000", steps[0][1])

    def test_plan_empty_root(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(full.plan(Path(td)), [])


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
            full._pull_cmd("user@srchost"),
            [
                "rsync",
                "-a",
                f"user@srchost:{paths.BACKUP_ROOT}/",
                f"{full.PULL_STAGE}/",
            ],
        )

    def test_host_with_explicit_path(self):
        self.assertEqual(
            full._pull_cmd("host:/custom/root"),
            ["rsync", "-a", "host:/custom/root/", f"{full.PULL_STAGE}/"],
        )


if __name__ == "__main__":
    unittest.main()
