"""Unit tests for cli.administration.recover.remote (host + device sources)."""

from __future__ import annotations

import unittest

from cli.administration.recover import remote


class SplitHostTest(unittest.TestCase):
    def test_splits_at_first_colon(self):
        self.assertEqual(
            remote.split_host("user@host:/dev/sdb1:usb"), ("user@host", "/dev/sdb1:usb")
        )


class RerootTest(unittest.TestCase):
    def test_keeps_relative_segments_drops_absolute_appends_root(self):
        self.assertEqual(
            remote._reroot(
                "/dev/sdb1:usb:20260710153000:/old", "/dev/sdb1", "/tmp/new"
            ),
            "/dev/sdb1:usb:20260710153000:/tmp/new",
        )


class CommandsTest(unittest.TestCase):
    def test_block_device_uses_ssh_then_pull(self):
        steps, root = remote.commands(
            "user@host:/dev/sdb1:usb", service_backup=True, passphrase_stdin=False
        )
        self.assertEqual(root, remote.LOCAL_ROOT)
        self.assertEqual(steps[0][:2], ["ssh", "user@host"])
        self.assertIn(remote.REMOTE_ROOT, steps[0][2])
        self.assertEqual(steps[1][0], "rsync")
        self.assertIn(f"user@host:{remote.REMOTE_ROOT}/", steps[1])

    def test_image_pulls_then_recovers_locally(self):
        steps, root = remote.commands(
            "host:/backup/usb.img", service_backup=True, passphrase_stdin=True
        )
        self.assertEqual(root, remote.LOCAL_ROOT)
        self.assertEqual(
            steps[0], ["rsync", "-a", "host:/backup/usb.img", remote.IMAGE]
        )
        self.assertEqual(steps[1][0], "python3")
        self.assertIn(remote.IMAGE, steps[1])
        self.assertIn(remote.LOCAL_ROOT, steps[1])
        self.assertIn("--passphrase-stdin", steps[1])


if __name__ == "__main__":
    unittest.main()
