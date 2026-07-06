import tempfile
import unittest
from pathlib import Path

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

    def test_address_is_valid_v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            address = ensure_node_onion(Path(tmp))
            self.assertTrue(address.endswith(".onion"))
            self.assertEqual(len(address) - len(".onion"), 56)


if __name__ == "__main__":
    unittest.main()
