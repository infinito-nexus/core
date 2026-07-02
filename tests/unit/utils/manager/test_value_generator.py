import base64
import re
import unittest

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from utils.manager.value_generator import ValueGenerator


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class TestValueGenerator(unittest.TestCase):
    def setUp(self):
        self.vg = ValueGenerator()

    def test_generate_secure_alphanumeric(self):
        s = self.vg.generate_secure_alphanumeric(64)
        self.assertEqual(len(s), 64)
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9]{64}", s))

    def test_generate_value_random_hex(self):
        v = self.vg.generate_value("random_hex")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{128}", v))

    def test_generate_value_random_hex_32(self):
        v = self.vg.generate_value("random_hex_32")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", v))

    def test_generate_value_random_hex_16(self):
        v = self.vg.generate_value("random_hex_16")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", v))

    def test_generate_value_sha256(self):
        v = self.vg.generate_value("sha256")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", v))

    def test_generate_value_sha1(self):
        v = self.vg.generate_value("sha1")
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", v))

    def test_generate_value_base64_prefixed_32(self):
        v = self.vg.generate_value("base64_prefixed_32")
        self.assertTrue(v.startswith("base64:"))
        raw = v.split("base64:", 1)[1].encode()
        decoded = base64.b64decode(raw)
        self.assertEqual(len(decoded), 32)

    def test_generate_value_alphanumeric(self):
        v = self.vg.generate_value("alphanumeric")
        self.assertEqual(len(v), 64)
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9]{64}", v))

    def test_generate_value_bcrypt(self):
        v = self.vg.generate_value("bcrypt")
        self.assertNotIn("$", v)
        self.assertGreater(len(v), 20)

    def test_generate_value_unknown(self):
        v = self.vg.generate_value("does_not_exist")
        self.assertEqual(v, "undefined")

    def test_generate_value_vapid_private(self):
        v = self.vg.generate_value("vapid_private")
        self.assertTrue(re.fullmatch(r"[-_A-Za-z0-9]{43}", v))
        self.assertEqual(len(_b64url_decode(v)), 32)

    def test_generate_value_vapid_public(self):
        v = self.vg.generate_value("vapid_public")
        self.assertTrue(re.fullmatch(r"[-_A-Za-z0-9]{87}", v))
        point = _b64url_decode(v)
        self.assertEqual(len(point), 65)
        self.assertEqual(point[0], 0x04)

    def test_vapid_keypair_is_cached(self):
        self.assertEqual(
            self.vg.generate_vapid_keypair(), self.vg.generate_vapid_keypair()
        )

    def test_vapid_private_and_public_are_linked(self):
        private, public = self.vg.generate_vapid_keypair()
        scalar = int.from_bytes(_b64url_decode(private), "big")
        derived = ec.derive_private_key(scalar, ec.SECP256R1())
        expected_point = derived.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        self.assertEqual(_b64url_decode(public), expected_point)


if __name__ == "__main__":
    unittest.main()
