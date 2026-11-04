"""Unit test: the existing-fix finder returns the first commit sha from an
oneline ref search and None when the search found nothing."""

from __future__ import annotations

import unittest

from agents.routines.tools.fixes import existing_fix

_SEARCH_OUTPUT = """bc6e3d228a feat(agents): implement the maintainer routine behavior layer
e76311b76d feat(agents): aggregate every agent role's cron schedule
"""

_WITH_WARNING = """warning: inexact rename detection was skipped
d3b9ae59a9 fix(users): token on the updater line
"""


class TestExistingFix(unittest.TestCase):
    def test_first_sha_returned(self) -> None:
        self.assertEqual(existing_fix(_SEARCH_OUTPUT), "bc6e3d228a")

    def test_skips_non_sha_lines(self) -> None:
        self.assertEqual(existing_fix(_WITH_WARNING), "d3b9ae59a9")

    def test_none_when_empty(self) -> None:
        self.assertIsNone(existing_fix(""))

    def test_none_when_no_sha(self) -> None:
        self.assertIsNone(existing_fix("no commits found\n"))


if __name__ == "__main__":
    unittest.main()
