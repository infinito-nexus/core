import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli.administration.inventory.onion import ensure_node_onion, identity_hs_dir

HS_NAMES = ("hostname", "hs_ed25519_public_key", "hs_ed25519_secret_key")


class TestEnsureNodeOnion(unittest.TestCase):
    def test_writes_authoritative_key_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            address = ensure_node_onion(tmp)
            hs = identity_hs_dir(tmp)
            for name in HS_NAMES:
                self.assertTrue((hs / name).exists(), name)
            self.assertEqual(
                (hs / "hostname").read_text().strip(),  # nocheck: cache-read -- tempdir
                address,
            )
            self.assertEqual(
                (hs / "hs_ed25519_secret_key").stat().st_mode & 0o777, 0o600
            )

    def test_reuses_existing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = ensure_node_onion(tmp)
            second = ensure_node_onion(tmp)
            self.assertEqual(first, second)

    def _chown_calls(self, base: Path) -> list:
        with (
            mock.patch("os.geteuid", return_value=0),
            mock.patch("os.lchown") as chown,
        ):
            ensure_node_onion(base)
        return chown.call_args_list

    def test_root_hands_the_identity_back_to_the_checkout_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            owner = base.stat()
            if owner.st_uid == 0:
                self.skipTest("checkout already belongs to root; nothing to hand back")
            calls = self._chown_calls(base)
            targets = {call.args[0] for call in calls}
            hs = identity_hs_dir(base)
            self.assertIn(base / ".onion-identity", targets)
            for name in HS_NAMES:
                self.assertIn(hs / name, targets)
            for call in calls:
                self.assertEqual(call.args[1:], (owner.st_uid, owner.st_gid))

    def test_the_reuse_path_repairs_ownership_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            if base.stat().st_uid == 0:
                self.skipTest("checkout already belongs to root; nothing to hand back")
            ensure_node_onion(base)
            self.assertTrue(self._chown_calls(base))

    def test_a_vanished_path_does_not_abort_the_provisioner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            if base.stat().st_uid == 0:
                self.skipTest("checkout already belongs to root; nothing to hand back")
            with (
                mock.patch("os.geteuid", return_value=0),
                mock.patch("os.lchown", side_effect=FileNotFoundError),
            ):
                address = ensure_node_onion(base)
            self.assertTrue(address.endswith(".onion"))

    def test_unprivileged_never_chowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch("os.geteuid", return_value=1000),
                mock.patch("os.lchown") as chown,
            ):
                ensure_node_onion(tmp)
            chown.assert_not_called()

    def test_address_is_valid_v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            address = ensure_node_onion(Path(tmp))
            self.assertTrue(address.endswith(".onion"))
            self.assertEqual(len(address) - len(".onion"), 56)


if __name__ == "__main__":
    unittest.main()
