import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.onion import identity_hs_dir, init_env

HS_NAMES = ("hostname", "hs_ed25519_public_key", "hs_ed25519_secret_key")


class TestInitEnv(unittest.TestCase):
    def test_upsert_preserves_and_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("FOO=bar\nINFINITO_DOMAIN=infinito.example\nBAZ=qux\n")
            address = init_env(env)
            txt = env.read_text()  # nocheck: cache-read -- synthetic tempdir file
            self.assertIn("FOO=bar", txt)
            self.assertIn("BAZ=qux", txt)
            self.assertEqual(txt.count("INFINITO_DOMAIN="), 1)
            self.assertIn(f"INFINITO_DOMAIN={address}", txt)
            expected_re = address.replace(".", "\\\\.")
            self.assertIn(f'INFINITO_DOMAIN_RE="{expected_re}"', txt)

    def test_writes_authoritative_key_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            address = init_env(env)
            hs = identity_hs_dir(env.parent)
            for name in HS_NAMES:
                self.assertTrue((hs / name).exists(), name)
            self.assertEqual(
                (hs / "hostname").read_text().strip(),  # nocheck: cache-read -- tempdir
                address,
            )
            self.assertEqual(
                (hs / "hs_ed25519_secret_key").stat().st_mode & 0o777, 0o600
            )

    def test_address_is_valid_v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            address = init_env(Path(tmp) / ".env")
            self.assertTrue(address.endswith(".onion"))
            self.assertEqual(len(address) - len(".onion"), 56)


if __name__ == "__main__":
    unittest.main()
