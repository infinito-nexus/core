import base64
import hashlib
import unittest

from utils.tor_onion import (
    PUBLIC_KEY_HEADER,
    SECRET_KEY_HEADER,
    mint,
    mint_from_seed_b64,
    onion_address,
)

# Deterministic test vector: seed 00,01,...,1f -> known v3 address.
VECTOR_SEED = bytes(range(32))
VECTOR_ADDRESS = "aoqqpp7tzyil4hlq3umoos6atft6jvrqtosq2xy53sdgiesvgg4bqead.onion"


class TestTorOnion(unittest.TestCase):
    def test_known_vector_address(self):
        self.assertEqual(mint(VECTOR_SEED).address, VECTOR_ADDRESS)

    def test_deterministic(self):
        self.assertEqual(mint(VECTOR_SEED).address, mint(VECTOR_SEED).address)
        self.assertEqual(mint(VECTOR_SEED).secret_key, mint(VECTOR_SEED).secret_key)

    def test_random_seed_unique_and_valid(self):
        a, b = mint(), mint()
        self.assertNotEqual(a.address, b.address)
        for k in (a, b):
            self.assertTrue(k.address.endswith(".onion"))
            self.assertEqual(len(k.address) - len(".onion"), 56)

    def test_file_formats(self):
        k = mint(VECTOR_SEED)
        files = k.files()
        self.assertEqual(
            set(files),
            {
                "hostname",
                "hs_ed25519_public_key",
                "hs_ed25519_secret_key",
            },
        )
        self.assertEqual(files["hostname"], (VECTOR_ADDRESS + "\n").encode())
        # public: 32-byte header + 32-byte key
        self.assertTrue(files["hs_ed25519_public_key"].startswith(PUBLIC_KEY_HEADER))
        self.assertEqual(len(files["hs_ed25519_public_key"]), 64)
        # secret: 32-byte header + 64-byte expanded key
        self.assertTrue(files["hs_ed25519_secret_key"].startswith(SECRET_KEY_HEADER))
        self.assertEqual(len(files["hs_ed25519_secret_key"]), 96)

    def test_expanded_secret_is_clamped(self):
        k = mint(VECTOR_SEED)
        expanded = k.secret_key[len(SECRET_KEY_HEADER) :]
        h = bytearray(hashlib.sha512(VECTOR_SEED).digest())
        h[0] &= 248
        h[31] &= 127
        h[31] |= 64
        self.assertEqual(expanded, bytes(h))

    def test_address_roundtrip(self):
        k = mint(VECTOR_SEED)
        raw = base64.b32decode(k.address[: -len(".onion")].upper())
        pub, checksum, version = raw[:32], raw[32:34], raw[34:35]
        self.assertEqual(version, b"\x03")
        expected = hashlib.sha3_256(b".onion checksum" + pub + version).digest()[:2]
        self.assertEqual(checksum, expected)
        self.assertEqual(onion_address(pub), k.address)

    def test_mint_from_seed_b64(self):
        seed_b64 = base64.b64encode(VECTOR_SEED).decode()
        self.assertEqual(mint_from_seed_b64(seed_b64).address, VECTOR_ADDRESS)

    def test_invalid_seed_length(self):
        with self.assertRaises(ValueError):
            mint(b"tooshort")

    def test_invalid_public_key_length(self):
        with self.assertRaises(ValueError):
            onion_address(b"\x00" * 31)


if __name__ == "__main__":
    unittest.main()
