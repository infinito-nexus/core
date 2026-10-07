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
        password = "A" * 64
        hashed = self.f(password)
        self.assertTrue(
            bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        )

    def test_72_byte_password_hashes_successfully(self):
        password = "A" * 72
        hashed = self.f(password)
        self.assertTrue(
            bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        )

    def test_73_byte_password_raises(self):
        with self.assertRaisesRegex(ValueError, "73 bytes.*at most 72 bytes"):
            self.f("A" * 73)

    def test_multibyte_password_over_72_bytes_raises(self):
        password = "ä" * 37
        self.assertEqual(len(password), 37)
        with self.assertRaisesRegex(ValueError, "74 bytes"):
            self.f(password)

    def test_same_secret_and_seed_give_the_same_hash(self):
        self.assertEqual(
            self.f("same-password", "app:indexer-admin"),
            self.f("same-password", "app:indexer-admin"),
        )

    def test_different_seed_gives_a_different_hash(self):
        self.assertNotEqual(
            self.f("same-password", "app:indexer-admin"),
            self.f("same-password", "app:dashboard-service"),
        )

    def test_different_secret_gives_a_different_hash(self):
        self.assertNotEqual(
            self.f("password-one", "app:indexer-admin"),
            self.f("password-two", "app:indexer-admin"),
        )

    def test_seeded_hash_verifies_against_the_original_password(self):
        password = "correct horse battery staple"
        hashed = self.f(password, "app:indexer-admin")
        self.assertTrue(
            bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        )
        self.assertTrue(hashed.startswith("$2b$12$"))

    def test_no_seed_stays_randomized(self):
        self.assertNotEqual(self.f("same-password"), self.f("same-password"))

    def test_empty_seed_raises(self):
        with self.assertRaises(ValueError):
            self.f("some-password", "")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            self.f(None)

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            self.f("")


if __name__ == "__main__":
    unittest.main()
