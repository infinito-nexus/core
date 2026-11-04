from __future__ import annotations

import tempfile
import unittest
from argparse import ArgumentParser
from pathlib import Path

from cli.administration.deploy.dedicated import modes
from cli.administration.deploy.dedicated.paths import MODES_FILE


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


def _load(content: str) -> list[dict]:
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
        path = f.name
        f.write(content)
        f.flush()
    try:
        return modes.load_modes_from_yaml(path)
    finally:
        Path(path).unlink()


class TestLoadModesFromYaml(unittest.TestCase):
    def test_load_modes_basic(self):
        parsed = _load(
            "CLEANUP: true   # cleanup before deploy\n"
            "DEBUG: false    # debug output\n"
            "VALIDATE: null  # inventory assertion\n"
        )

        by_name = {m["name"]: m for m in parsed}
        self.assertEqual(set(by_name), {"CLEANUP", "DEBUG", "VALIDATE"})
        self.assertEqual(by_name["CLEANUP"]["default"], True)
        self.assertEqual(by_name["DEBUG"]["default"], False)
        self.assertIsNone(by_name["VALIDATE"]["default"])
        self.assertEqual(by_name["CLEANUP"]["help"], "cleanup before deploy")

    def test_every_key_is_a_mode(self):
        parsed = _load("---\n# Mode\nFOO: true\nBAR: false\n")

        self.assertEqual([m["name"] for m in parsed], ["FOO", "BAR"])


class TestDynamicModes(unittest.TestCase):
    def setUp(self):
        self.modes_meta = [
            {"name": "CLEANUP", "default": True, "help": "Cleanup before run"},
            {"name": "DEBUG", "default": False, "help": "Debug output"},
            {"name": "VALIDATE", "default": None, "help": "Inventory assertion"},
        ]

    def _resolve(self, *argv: str) -> dict:
        parser = ArgumentParser()
        spec = modes.add_dynamic_mode_args(parser, self.modes_meta)
        self.assertEqual(set(spec), {"CLEANUP", "DEBUG", "VALIDATE"})
        return modes.build_modes_from_args(spec, parser.parse_args(list(argv)))

    def test_defaults(self):
        resolved = self._resolve()

        self.assertTrue(resolved["CLEANUP"])
        self.assertFalse(resolved["DEBUG"])
        self.assertNotIn("VALIDATE", resolved)

    def test_flags_true(self):
        resolved = self._resolve("--skip-cleanup", "--debug", "--validate", "true")

        self.assertFalse(resolved["CLEANUP"])
        self.assertTrue(resolved["DEBUG"])
        self.assertTrue(resolved["VALIDATE"])

    def test_flags_false_explicit(self):
        resolved = self._resolve("--validate", "false")

        self.assertTrue(resolved["CLEANUP"])
        self.assertFalse(resolved["DEBUG"])
        self.assertIs(resolved["VALIDATE"], False)

    def test_the_removed_assert_flag_is_rejected(self):
        parser = ArgumentParser()
        modes.add_dynamic_mode_args(parser, self.modes_meta)

        with self.assertRaises(SystemExit):
            parser.parse_args(["--assert", "true"])


class TestProjectModesFile(unittest.TestCase):
    def test_flags_are_the_lowercased_keys(self):
        parser = ArgumentParser()
        modes.add_dynamic_mode_args(parser, modes.load_modes_from_yaml(MODES_FILE))
        flags = {
            option
            for action in parser._actions
            for option in action.option_strings
            if option not in ("-h", "--help")
        }

        self.assertEqual(
            flags,
            {
                "--dummy",
                "--debug",
                "--reset",
                "--skip-cleanup",
                "--validate",
                "--skip-backup",
                "--demo",
            },
        )


if __name__ == "__main__":
    unittest.main()
