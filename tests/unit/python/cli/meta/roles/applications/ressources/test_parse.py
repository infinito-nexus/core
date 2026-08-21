from __future__ import annotations

import unittest

from utils.roles.applications.services import resources as cli


class TestParsingHelpers(unittest.TestCase):
    def test_parse_mem_bytes_handles_various_units(self) -> None:
        self.assertEqual(cli._parse_mem_bytes("1g"), 1_000_000_000)
        self.assertEqual(cli._parse_mem_bytes("512m"), 512_000_000)
        self.assertEqual(cli._parse_mem_bytes("256M"), 256_000_000)
        self.assertEqual(cli._parse_mem_bytes(1024), 1024)
        self.assertIsNone(cli._parse_mem_bytes(None))
        self.assertIsNone(cli._parse_mem_bytes(""))
        self.assertIsNone(cli._parse_mem_bytes("not-a-size"))

    def test_parse_cpus(self) -> None:
        self.assertEqual(cli._parse_cpus(4), 4.0)
        self.assertEqual(cli._parse_cpus("2.0"), 2.0)
        self.assertEqual(cli._parse_cpus("0.5"), 0.5)
        self.assertIsNone(cli._parse_cpus(None))
        self.assertIsNone(cli._parse_cpus("abc"))

    def test_parse_int(self) -> None:
        self.assertEqual(cli._parse_int(2048), 2048)
        self.assertEqual(cli._parse_int("1024"), 1024)
        self.assertIsNone(cli._parse_int(None))
        self.assertIsNone(cli._parse_int(True))
        self.assertIsNone(cli._parse_int("not-int"))

    def test_parse_bond_parses_numbers_and_rejects_junk(self) -> None:
        self.assertEqual(cli._parse_bond(1), 1.0)
        self.assertEqual(cli._parse_bond(0.5), 0.5)
        self.assertEqual(cli._parse_bond("0.25"), 0.25)
        self.assertIsNone(cli._parse_bond(None))
        self.assertIsNone(cli._parse_bond(True))
        self.assertIsNone(cli._parse_bond("nope"))

    def test_is_enabled_returns_passed_default_when_key_missing(self) -> None:
        self.assertTrue(cli._is_enabled({}, default_enabled=True))
        self.assertFalse(cli._is_enabled({}, default_enabled=False))

    def test_is_enabled_respects_explicit_flag(self) -> None:
        self.assertTrue(cli._is_enabled({"enabled": True}, default_enabled=False))
        self.assertFalse(cli._is_enabled({"enabled": False}, default_enabled=True))
        self.assertFalse(cli._is_enabled({"enabled": "false"}, default_enabled=True))
        self.assertFalse(cli._is_enabled({"enabled": "0"}, default_enabled=True))

    def test_is_enabled_treats_template_strings_as_truthy(self) -> None:
        self.assertTrue(
            cli._is_enabled(
                {"enabled": "{{ RECAPTCHA_ENABLED | bool }}"},
                default_enabled=False,
            )
        )

    def test_is_shared(self) -> None:
        self.assertTrue(cli._is_shared({"shared": True}))
        self.assertTrue(cli._is_shared({"shared": "true"}))
        self.assertFalse(cli._is_shared({}))
        self.assertFalse(cli._is_shared({"shared": False}))

    def test_looks_like_container(self) -> None:
        self.assertTrue(cli._looks_like_container({"mem_limit": "256m"}))
        self.assertTrue(cli._looks_like_container({"cpus": 1}))
        self.assertTrue(cli._looks_like_container({"image": "alpine"}))
        self.assertTrue(cli._looks_like_container({"name": "foo", "version": "1"}))
        self.assertFalse(cli._looks_like_container({}))
        self.assertFalse(cli._looks_like_container({"enabled": True}))


if __name__ == "__main__":
    unittest.main()
