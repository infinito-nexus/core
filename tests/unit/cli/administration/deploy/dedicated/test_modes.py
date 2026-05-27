from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.deploy.dedicated import modes


class TestParseBoolLiteral(unittest.TestCase):
    def test_true_values(self):
        self.assertTrue(modes._parse_bool_literal("true"))
        self.assertTrue(modes._parse_bool_literal("True"))
        self.assertTrue(modes._parse_bool_literal(" yes "))
        self.assertTrue(modes._parse_bool_literal("ON"))

    def test_false_values(self):
        self.assertFalse(modes._parse_bool_literal("false"))
        self.assertFalse(modes._parse_bool_literal("False"))
        self.assertFalse(modes._parse_bool_literal(" no "))
        self.assertFalse(modes._parse_bool_literal("off"))

    def test_unknown_value(self):
        self.assertIsNone(modes._parse_bool_literal("maybe"))
        self.assertIsNone(modes._parse_bool_literal(""))
        self.assertIsNone(modes._parse_bool_literal("  "))


class TestLoadModesFromYaml(unittest.TestCase):
    def test_load_modes_basic(self):
        content = """\
MODE_CLEANUP: true   # cleanup before deploy
MODE_DEBUG: false    # debug output
MODE_ASSERT: null    # inventory assertion
OTHER_KEY: true      # should be ignored (no MODE_ prefix)
"""

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            path = f.name
            f.write(content)
            f.flush()

        try:
            parsed = modes.load_modes_from_yaml(path)
        finally:
            Path(path).unlink()

        self.assertEqual(len(parsed), 3)
        by_name = {m["name"]: m for m in parsed}

        self.assertIn("MODE_CLEANUP", by_name)
        self.assertIn("MODE_DEBUG", by_name)
        self.assertIn("MODE_ASSERT", by_name)

        self.assertEqual(by_name["MODE_CLEANUP"]["default"], True)
        self.assertEqual(by_name["MODE_DEBUG"]["default"], False)
        self.assertIsNone(by_name["MODE_ASSERT"]["default"])
        self.assertEqual(by_name["MODE_CLEANUP"]["help"], "cleanup before deploy")

    def test_load_modes_ignores_non_mode_keys(self):
        content = """\
FOO: true
BAR: false
MODE_FOO: true
"""

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            path = f.name
            f.write(content)
            f.flush()

        try:
            parsed = modes.load_modes_from_yaml(path)
        finally:
            Path(path).unlink()

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "MODE_FOO")


class TestDynamicModes(unittest.TestCase):
    def setUp(self):
        self.modes_meta = [
            {"name": "MODE_CLEANUP", "default": True, "help": "Cleanup before run"},
            {"name": "MODE_DEBUG", "default": False, "help": "Debug output"},
            {"name": "MODE_ASSERT", "default": None, "help": "Inventory assertion"},
        ]

    def test_add_dynamic_mode_args_and_build_modes_defaults(self):
        from argparse import ArgumentParser

        parser = ArgumentParser()
        spec = modes.add_dynamic_mode_args(parser, self.modes_meta)

        self.assertIn("MODE_CLEANUP", spec)
        self.assertIn("MODE_DEBUG", spec)
        self.assertIn("MODE_ASSERT", spec)

        # No flags passed → defaults apply
        args = parser.parse_args([])
        resolved = modes.build_modes_from_args(spec, args)

        self.assertTrue(resolved["MODE_CLEANUP"])  # default True
        self.assertFalse(resolved["MODE_DEBUG"])  # default False
        self.assertNotIn("MODE_ASSERT", resolved)  # explicit, not set

    def test_add_dynamic_mode_args_and_build_modes_flags_true(self):
        from argparse import ArgumentParser

        parser = ArgumentParser()
        spec = modes.add_dynamic_mode_args(parser, self.modes_meta)

        # MODE_CLEANUP: true   → --skip-cleanup  sets it to False
        # MODE_DEBUG:   false  → --debug        sets it to True
        # MODE_ASSERT:  None   → --assert true  sets it to True
        args = parser.parse_args(["--skip-cleanup", "--debug", "--assert", "true"])
        resolved = modes.build_modes_from_args(spec, args)

        self.assertFalse(resolved["MODE_CLEANUP"])
        self.assertTrue(resolved["MODE_DEBUG"])
        self.assertTrue(resolved["MODE_ASSERT"])

    def test_add_dynamic_mode_args_and_build_modes_flags_false_explicit(self):
        from argparse import ArgumentParser

        parser = ArgumentParser()
        spec = modes.add_dynamic_mode_args(parser, self.modes_meta)

        # explicit false for MODE_ASSERT
        args = parser.parse_args(["--assert", "false"])
        resolved = modes.build_modes_from_args(spec, args)

        self.assertTrue(resolved["MODE_CLEANUP"])  # still default True
        self.assertFalse(resolved["MODE_DEBUG"])  # still default False
        self.assertIn("MODE_ASSERT", resolved)
        self.assertFalse(resolved["MODE_ASSERT"])


if __name__ == "__main__":
    unittest.main()
