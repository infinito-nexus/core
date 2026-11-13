from __future__ import annotations

import unittest

from utils.docker.digest import valid_digest

SHA256 = "sha256:" + "d" * 64
SHA512 = "sha512:" + "f" * 128


class TestValidDigest(unittest.TestCase):
    def test_well_formed_sha256_and_sha512_pass(self) -> None:
        self.assertEqual(valid_digest(SHA256), SHA256)
        self.assertEqual(valid_digest(SHA512), SHA512)

    def test_anything_that_could_name_another_path_is_dropped(self) -> None:
        for value in (
            "sha256:/../../etc",
            "sha256:" + "d" * 63 + "/",
            "sha256:" + "D" * 64,
            "sha256:" + "d" * 64 + "\n",
            "md5:" + "d" * 32,
            "",
            None,
            42,
        ):
            with self.subTest(value=value):
                self.assertIsNone(valid_digest(value))


if __name__ == "__main__":
    unittest.main()
