from __future__ import annotations

import unittest

from cli.administration.deploy import dedicated as deploy
from cli.administration.deploy.dedicated import modes


class TestDedicatedInitExports(unittest.TestCase):
    def test_main_is_exported(self):
        self.assertTrue(callable(deploy.main))

    def test_parse_bool_literal_is_reexported_from_modes(self):
        self.assertIs(deploy._parse_bool_literal, modes._parse_bool_literal)
        self.assertTrue(deploy._parse_bool_literal("true"))
        self.assertFalse(deploy._parse_bool_literal("false"))
        self.assertIsNone(deploy._parse_bool_literal("maybe"))


if __name__ == "__main__":
    unittest.main()
