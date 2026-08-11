import unittest

import bcrypt

from plugins.filter.bcrypt_hash import FilterModule


class TestBcryptHash(unittest.TestCase):
    def setUp(self):
        self.f = FilterModule().filters()["bcrypt_hash"]

    def test_hash_verifies_against_the_original_password(self):
        password = "correct horse battery staple"
        hashed = self.f(password)
        self.assertTrue(
            bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        )

    def test_hash_does_not_verify_against_a_different_password(self):
        hashed = self.f("password-one")
        self.assertFalse(bcrypt.checkpw(b"password-two", hashed.encode("utf-8")))

    def test_hash_is_randomized_salt_each_call(self):
        password = "same-password"
        self.assertNotEqual(self.f(password), self.f(password))

    def test_hash_has_bcrypt_prefix(self):
        hashed = self.f("some-password")
        self.assertTrue(hashed.startswith(("$2b$", "$2a$")))

    def test_64_character_password_hashes_successfully(self):
        # Regression: Ansible's password_hash('bcrypt') filter routes through
        # passlib, whose bcrypt self-test can misreport a well-under-72-byte
        # password as "too long" when passlib and the installed bcrypt
        # package's version detection drift apart. The raw bcrypt package
        # used here has no such self-test.
        password = "A" * 64
        hashed = self.f(password)
        self.assertTrue(
            bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        )

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            self.f(None)

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            self.f("")


if __name__ == "__main__":
    unittest.main()
