"""Lint guard: the shortcut table in
``docs/contributing/tools/agents/alias.md`` (the agent conversation
shortcuts). Every shortcut MUST start with ``ai8``, MUST NOT place more
than two consonants next to each other, and the table MUST stay sorted
ascending so operators can scan and extend it predictably.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.terminal_aliases import alias_md_file

ROW_RE = re.compile(r"^\|\s*`(?P<shortcut>[^`]+)`\s*\|")
VOWELS = frozenset("aeiou")


def _has_consonant_cluster(name: str) -> bool:
    run = 0
    for char in name:
        if not char.isalpha():
            run = 0
            continue
        run = run + 1 if char.lower() not in VOWELS else 0
        if run > 2:
            return True
    return False


class TestAliasTable(unittest.TestCase):
    def setUp(self):
        alias_md = alias_md_file()
        self.assertTrue(alias_md.is_file(), f"agent alias markdown missing: {alias_md}")
        self.alias_md = alias_md
        self.shortcuts = [
            match.group("shortcut")
            for line in read_text(str(alias_md)).splitlines()
            if (match := ROW_RE.match(line))
        ]
        self.assertTrue(
            self.shortcuts,
            f"No shortcut rows found in {alias_md}; expected a markdown "
            "table whose first column holds backtick-quoted shortcuts.",
        )

    def test_shortcuts_sorted_ascending(self):
        self.assertEqual(
            self.shortcuts,
            sorted(self.shortcuts),
            f"Shortcut table in {self.alias_md} is not sorted ascending. "
            f"Expected order: {sorted(self.shortcuts)}",
        )

    def test_shortcuts_start_with_ai8(self):
        bad = [s for s in self.shortcuts if not s.startswith("ai8")]
        self.assertFalse(bad, f"shortcuts not starting with 'ai8': {bad}")

    def test_no_consecutive_consonants(self):
        bad = [s for s in self.shortcuts if _has_consonant_cluster(s)]
        self.assertFalse(
            bad, f"shortcuts with more than two adjacent consonants: {bad}"
        )


if __name__ == "__main__":
    unittest.main()
