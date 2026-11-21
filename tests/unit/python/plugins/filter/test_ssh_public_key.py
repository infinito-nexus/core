import unittest

from ansible.errors import AnsibleFilterError
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from plugins.filter.ssh_public_key import FilterModule


class TestSshPublicKey(unittest.TestCase):
    def setUp(self):
        self.f = FilterModule().filters()["ssh_public_key"]
        self.key = ed25519.Ed25519PrivateKey.generate()
        self.private = self.key.private_bytes(
            Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
        ).decode()

    def test_it_returns_the_authorized_keys_line_of_the_public_half(self):
        expected = (
            self.key.public_key()
            .public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
            .decode()
        )
        self.assertEqual(self.f(self.private), expected)
        self.assertTrue(self.f(self.private).startswith("ssh-ed25519 "))

    def test_it_never_returns_private_material(self):
        self.assertNotIn("PRIVATE", self.f(self.private))

    def test_a_value_that_is_no_openssh_key_fails_loudly(self):
        with self.assertRaises(AnsibleFilterError):
            self.f("not a key")


if __name__ == "__main__":
    unittest.main()
