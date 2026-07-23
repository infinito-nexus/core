from __future__ import annotations

import unittest

from cli.build.readme.overview import (
    ANCHOR_HEADING,
    SECTION_HEADING,
    _cell,
    replace_section,
)

_README = f"""# Repo

Intro.

{ANCHOR_HEADING}

Body.

## Guides 📚

More.
"""


class TestReplaceSection(unittest.TestCase):
    def test_inserts_below_anchor_before_next_heading(self) -> None:
        result = replace_section(_README, "| a |")
        self.assertGreater(result.index(SECTION_HEADING), result.index(ANCHOR_HEADING))
        self.assertLess(result.index(SECTION_HEADING), result.index("## Guides 📚"))
        self.assertIn("| a |", result)

    def test_replaces_existing_section_only(self) -> None:
        first = replace_section(_README, "| old |")
        second = replace_section(first, "| new |")
        self.assertNotIn("| old |", second)
        self.assertIn("| new |", second)
        self.assertEqual(second.count(SECTION_HEADING), 1)
        self.assertIn("## Guides 📚", second)

    def test_idempotent(self) -> None:
        first = replace_section(_README, "| t |")
        self.assertEqual(replace_section(first, "| t |"), first)

    def test_missing_anchor_raises(self) -> None:
        with self.assertRaises(ValueError):
            replace_section("# Repo\n\nNo anchor.\n", "| t |")


class TestCell(unittest.TestCase):
    def test_escapes_pipes_and_collapses_whitespace(self) -> None:
        self.assertEqual(_cell("a | b\nc"), "a \\| b c")


if __name__ == "__main__":
    unittest.main()
