"""Unit tests for the per-role ``files/recover.py`` CLIs that wrap
DirectoryRecovery: unit_pattern, the class behaviour (docker mountpoint
resolution, export mirror, snapshot selection across machine hashes,
service-backup-less device recovery) and the ``main()`` CLI wiring
(argparse -> Recovery construction -> run, incl. the LUKS orchestration
and its umount/luksClose cleanup)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import PROJECT_ROOT


def _load(role: str, name: str):
    path = PROJECT_ROOT / "roles" / role / "files" / "recover.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UnitPatternTests(unittest.TestCase):
    def test_each_subclass_declares_its_role_unit(self):
        cases = {
            (
                "svc-bkp-volume-2-local",
                "VolumeRecovery",
            ): "svc-bkp-volume-2-local*.service",
            (
                "svc-bkp-nfs-2-local",
                "NfsExportRecovery",
            ): "svc-bkp-nfs-2-local*.service",
            (
                "svc-bkp-local-2-device",
                "DeviceRecovery",
            ): "svc-bkp-local-2-device*.service",
        }
        for (role, cls), pattern in cases.items():
            mod = _load(role, role.replace("-", "_"))
            self.assertEqual(getattr(mod, cls).unit_pattern, pattern)


class VolumeRecoverTests(unittest.TestCase):
    def test_resolves_mountpoint_and_threads_flag(self):
        mod = _load("svc-bkp-volume-2-local", "volume_recover")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            mount = Path(td) / "mount"
            mount.mkdir()
            with mock.patch.object(
                mod.subprocess, "run", return_value=mock.Mock(stdout=f"{mount}\n")
            ) as run:
                rec = mod.VolumeRecovery(str(source), "myvol", service_backup=False)
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[:4], ["docker", "volume", "inspect", "--format"])
            self.assertEqual(cmd[-1], "myvol")
            self.assertEqual(rec.target_dir, mount)
            self.assertFalse(rec.service_backup)

    def test_main_wires_argparse_to_recovery(self):
        mod = _load("svc-bkp-volume-2-local", "volume_recover")
        for argv, expect_backup in (
            (["recover.py", "/snap", "vol"], True),
            (["recover.py", "/snap", "vol", "--no-safety-backup"], False),
        ):
            with (
                mock.patch.object(mod, "VolumeRecovery") as mock_vol,
                mock.patch.object(sys, "argv", argv),
            ):
                mock_vol.return_value.run.return_value = 0
                self.assertEqual(mod.main(), 0)
                mock_vol.assert_called_once_with(
                    "/snap", "vol", service_backup=expect_backup, docker_host=None
                )
                mock_vol.return_value.run.assert_called_once_with()


class NfsRecoverTests(unittest.TestCase):
    def test_restore_mirrors_snapshot_into_target(self):
        mod = _load("svc-bkp-nfs-2-local", "nfs_recover")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            target = Path(td) / "target"
            source.mkdir()
            target.mkdir()
            (source / "restored.txt").write_text("from-snapshot")
            (target / "stale.txt").write_text("pre-recover")
            mod.NfsExportRecovery(
                str(source), str(target), service_backup=False
            ).restore()
            self.assertEqual(
                (
                    target / "restored.txt"
                ).read_text(),  # nocheck: cache-read - tempdir fixture
                "from-snapshot",
            )
            self.assertFalse((target / "stale.txt").exists())

    def test_main_wires_argparse_to_recovery(self):
        mod = _load("svc-bkp-nfs-2-local", "nfs_recover")
        for argv, expect_backup in (
            (["recover.py", "/snap", "/export"], True),
            (["recover.py", "/snap", "/export", "--no-safety-backup"], False),
        ):
            with (
                mock.patch.object(mod, "NfsExportRecovery") as mock_nfs,
                mock.patch.object(sys, "argv", argv),
            ):
                mock_nfs.return_value.run.return_value = 0
                self.assertEqual(mod.main(), 0)
                mock_nfs.assert_called_once_with(
                    "/snap", "/export", service_backup=expect_backup
                )
                mock_nfs.return_value.run.assert_called_once_with()


class DeviceRecoverTests(unittest.TestCase):
    def _snap(self, mount: Path, machine_hash: str, ts: str) -> None:
        (mount / machine_hash / "svc-bkp-local-2-device" / ts).mkdir(parents=True)

    def test_newest_snapshot_picks_latest_across_hashes(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td)
            self._snap(mount, "hashA", "20240101000000")
            self._snap(mount, "hashA", "20240103000000")
            self._snap(mount, "hashB", "20240102000000")
            self.assertEqual(mod._newest_snapshot(mount, None).name, "20240103000000")

    def test_newest_snapshot_honours_explicit_timestamp(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td)
            self._snap(mount, "hashA", "20240101000000")
            self._snap(mount, "hashB", "20240103000000")
            self.assertEqual(
                mod._newest_snapshot(mount, "20240101000000").name, "20240101000000"
            )

    def test_newest_snapshot_refuses_when_absent(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td)
            with self.assertRaises(SystemExit):
                mod._newest_snapshot(mount, None)
            self._snap(mount, "hashA", "20240101000000")
            with self.assertRaises(SystemExit):
                mod._newest_snapshot(mount, "does-not-exist")

    def test_device_recovery_never_service_backs_up(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            target = Path(td) / "target"
            source.mkdir()
            target.mkdir()
            self.assertFalse(
                mod.DeviceRecovery(str(source), str(target)).service_backup
            )

    def test_main_luks_flow_stdin_passphrase_and_cleanup(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td) / "mnt"
            target = Path(td) / "target"
            target.mkdir()
            snapshot = Path(td) / "snap"
            calls: list[list[str]] = []

            with (
                mock.patch.object(
                    mod.subprocess,
                    "run",
                    side_effect=lambda cmd, **kw: calls.append(cmd),
                ),
                mock.patch.object(mod, "_newest_snapshot", return_value=snapshot),
                mock.patch.object(mod, "DeviceRecovery") as mock_dev,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "recover.py",
                        "dev.img",
                        str(mount),
                        str(target),
                        "--passphrase-stdin",
                    ],
                ),
            ):
                mock_dev.return_value.run.return_value = 0
                self.assertEqual(mod.main(), 0)

            mock_dev.assert_called_once_with(str(snapshot / "backup"), str(target))
            luks_open = next(c for c in calls if c[:2] == ["cryptsetup", "luksOpen"])
            self.assertIn("--key-file=-", luks_open)
            self.assertTrue(any(c[0] == "mount" for c in calls))
            self.assertTrue(any(c[:2] == ["umount", str(mount)] for c in calls))
            self.assertTrue(any(c[:2] == ["cryptsetup", "luksClose"] for c in calls))

    def test_main_device_target_scopes_the_snapshot_root(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td) / "mnt"
            target = Path(td) / "target"
            target.mkdir()
            with (
                mock.patch.object(mod.subprocess, "run"),
                mock.patch.object(
                    mod, "_newest_snapshot", return_value=Path(td) / "snap"
                ) as newest,
                mock.patch.object(mod, "DeviceRecovery") as mock_dev,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "recover.py",
                        "dev.img",
                        str(mount),
                        str(target),
                        "--device-target",
                        "/infinito",
                    ],
                ),
            ):
                mock_dev.return_value.run.return_value = 0
                self.assertEqual(mod.main(), 0)
            self.assertEqual(newest.call_args.args[0], mount / "infinito")

    def test_main_cleans_up_even_when_recover_raises(self):
        mod = _load("svc-bkp-local-2-device", "device_recover")
        with tempfile.TemporaryDirectory() as td:
            mount = Path(td) / "mnt"
            target = Path(td) / "target"
            target.mkdir()
            calls: list[list[str]] = []

            with (
                mock.patch.object(
                    mod.subprocess,
                    "run",
                    side_effect=lambda cmd, **kw: calls.append(cmd),
                ),
                mock.patch.object(
                    mod, "_newest_snapshot", return_value=Path(td) / "snap"
                ),
                mock.patch.object(
                    mod, "DeviceRecovery", side_effect=RuntimeError("boom")
                ),
                mock.patch.object(
                    sys, "argv", ["recover.py", "dev.img", str(mount), str(target)]
                ),
                self.assertRaises(RuntimeError),
            ):
                mod.main()

            self.assertTrue(any(c[:2] == ["umount", str(mount)] for c in calls))
            self.assertTrue(any(c[:2] == ["cryptsetup", "luksClose"] for c in calls))


if __name__ == "__main__":
    unittest.main()
