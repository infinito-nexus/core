"""Unit tests for cli.administration.recover.recoverers."""

from __future__ import annotations

import unittest

from cli.administration.recover import paths, recoverers


def _args(name: str, source: str, **kw) -> list[str]:
    return recoverers.RECOVERERS[name].command(source, **kw)[2:]


class NfsTest(unittest.TestCase):
    def test_default_target(self):
        self.assertEqual(_args("nfs", "/snap"), ["/snap", paths.NFS_EXPORT_STATE])

    def test_absolute_colon_target_overrides(self):
        self.assertEqual(
            _args("nfs", "/snap:/srv/nfs/infinito-state/matomo_data"),
            ["/snap", "/srv/nfs/infinito-state/matomo_data"],
        )

    def test_relative_colon_target_rejected(self):
        with self.assertRaises(ValueError):
            _args("nfs", "/snap:relative")

    def test_no_safety_backup(self):
        self.assertEqual(
            _args("nfs", "/snap", service_backup=False)[-1], "--no-safety-backup"
        )


class VolumeTest(unittest.TestCase):
    def test_name_from_source(self):
        self.assertEqual(
            _args("volume", "/g/pg_data/files"), ["/g/pg_data/files", "pg_data"]
        )


class SecretsTest(unittest.TestCase):
    def test_source_only(self):
        self.assertEqual(_args("secrets", "/gen/files"), ["/gen/files"])


class DeviceTest(unittest.TestCase):
    def test_bare_device_defaults(self):
        self.assertEqual(
            _args("device", "/dev/sdb1"),
            ["/dev/sdb1", paths.RECOVER_MOUNT, paths.BACKUP_ROOT],
        )

    def test_relative_subpath(self):
        self.assertEqual(
            _args("device", "/dev/sdb1:usb/gen"),
            [
                "/dev/sdb1",
                paths.RECOVER_MOUNT,
                paths.BACKUP_ROOT,
                "--device-target",
                "usb/gen",
            ],
        )

    def test_subpath_and_absolute_target(self):
        self.assertEqual(
            _args("device", "/img:usb/gen:/tmp/restore", passphrase_stdin=True),
            [
                "/img",
                paths.RECOVER_MOUNT,
                "/tmp/restore",
                "--device-target",
                "usb/gen",
                "--passphrase-stdin",
            ],
        )

    def test_absolute_target_only_empty_subpath(self):
        self.assertEqual(
            _args("device", "/img::/tmp/restore"),
            ["/img", paths.RECOVER_MOUNT, "/tmp/restore"],
        )

    def test_digit_segment_is_snapshot(self):
        self.assertEqual(
            _args("device", "/img:usb:20260710153000:/tmp/restore"),
            [
                "/img",
                paths.RECOVER_MOUNT,
                "/tmp/restore",
                "--device-target",
                "usb",
                "--snapshot",
                "20260710153000",
            ],
        )

    def test_no_safety_backup_never_for_device(self):
        self.assertNotIn(
            "--no-safety-backup", _args("device", "/dev/sdb1", service_backup=False)
        )


class RemoteTest(unittest.TestCase):
    def test_is_remote(self):
        self.assertFalse(recoverers.is_remote("/local/path"))
        self.assertTrue(recoverers.is_remote("user@host:/remote/path"))
        self.assertTrue(recoverers.is_remote("host:/remote/path"))

    def test_nfs_remote_source_passthrough_default_target(self):
        self.assertEqual(
            _args("nfs", "user@host:/remote/snap"),
            ["user@host:/remote/snap", paths.NFS_EXPORT_STATE],
        )

    def test_volume_remote_source(self):
        self.assertEqual(
            _args("volume", "host:/b/gen/pg_data/files"),
            ["host:/b/gen/pg_data/files", "pg_data"],
        )

    def test_device_rejects_remote(self):
        with self.assertRaises(ValueError):
            _args("device", "host:/dev/sdb1")

    def test_secrets_rejects_remote(self):
        with self.assertRaises(ValueError):
            _args("secrets", "host:/gen/files")


class RemoteTargetTest(unittest.TestCase):
    def test_nfs_remote_target_prefixes_host(self):
        self.assertEqual(
            _args("nfs", "/snap", target="user@host"),
            ["/snap", "user@host:/srv/nfs/infinito-state"],
        )

    def test_volume_remote_target_docker_host(self):
        self.assertEqual(
            _args("volume", "/g/pg_data/files", target="user@host"),
            ["/g/pg_data/files", "pg_data", "--docker-host", "ssh://user@host"],
        )

    def test_secrets_remote_target_flag(self):
        self.assertEqual(
            _args("secrets", "/gen/files", target="user@host"),
            ["/gen/files", "--target-host", "user@host"],
        )

    def test_localhost_stays_local(self):
        self.assertEqual(
            _args("nfs", "/snap", target="localhost"), ["/snap", paths.NFS_EXPORT_STATE]
        )


class RegistryTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(recoverers.ORDER, ("device", "nfs", "volume", "secrets"))

    def test_command_starts_with_interpreter_and_script(self):
        cmd = recoverers.RECOVERERS["secrets"].command("/gen/files")
        self.assertEqual(cmd[0], "python3")
        self.assertTrue(cmd[1].endswith("svc-bkp-secrets-2-local/files/recover.py"))


if __name__ == "__main__":
    unittest.main()
