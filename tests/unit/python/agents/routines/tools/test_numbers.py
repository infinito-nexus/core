"""Unit test: the number-backed check flags every number absent from the run's
evidence and leaves backed ones alone."""

from __future__ import annotations

import unittest

from agents.routines.tools.numbers import unbacked_numbers


class TestUnbackedNumbers(unittest.TestCase):
    def test_backed_numbers_pass(self) -> None:
        evidence = "42 tests passed in 3.14s, affected matrix size 7"
        self.assertEqual(unbacked_numbers("ran 42 tests, matrix 7", evidence), [])

    def test_unbacked_number_flagged(self) -> None:
        evidence = "42 tests passed in 3.14s"
        self.assertEqual(
            unbacked_numbers("fixed 5 bugs across 42 tests", evidence), ["5"]
        )

    def test_thousands_and_percent_normalised(self) -> None:
        evidence = "coverage 1000 lines, 80 percent of branches"
        self.assertEqual(unbacked_numbers("1,000 lines at 80%", evidence), [])

    def test_order_preserved_and_deduplicated(self) -> None:
        self.assertEqual(
            unbacked_numbers("9 then 9 then 8", "no digits here"), ["9", "8"]
        )


if __name__ == "__main__":
    unittest.main()
