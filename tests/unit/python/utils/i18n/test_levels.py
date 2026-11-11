"""Unit test: a language whose sampled chat-judge level falls below its last
accepted level gets no pull request, and a judge reply without a level aborts
its verification instead of being scored."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.i18n.judge import parse_level
from utils.i18n.levels import accepted_levels, gate


class TestTheLastAcceptedLevelGate(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_the_first_pass_becomes_the_baseline(self) -> None:
        self.assertEqual(gate(self.root, "de", [2, 2, 1, 2]), "")
        self.assertEqual(accepted_levels(self.root), {"de": 1.75})

    def test_a_level_below_the_last_accepted_gets_no_pull_request(self) -> None:
        gate(self.root, "de", [2, 2, 1, 2])

        why = gate(self.root, "de", [2, 1, 1, 2])

        self.assertIn("below its last accepted level 1.75", why)
        self.assertEqual(accepted_levels(self.root), {"de": 1.75})

    def test_an_equal_or_higher_level_passes_and_raises_the_baseline(self) -> None:
        gate(self.root, "de", [2, 2, 1, 2])

        self.assertEqual(gate(self.root, "de", [2, 2, 1, 2]), "")
        self.assertEqual(gate(self.root, "de", [2, 2, 2, 2]), "")
        self.assertEqual(accepted_levels(self.root), {"de": 2.0})

    def test_each_language_is_held_to_its_own_level(self) -> None:
        gate(self.root, "de", [2, 2])
        gate(self.root, "fr", [1, 1])

        self.assertEqual(gate(self.root, "fr", [1, 2]), "")
        self.assertNotEqual(gate(self.root, "de", [1, 2]), "")

    def test_a_reply_without_a_level_aborts_the_verification(self) -> None:
        gate(self.root, "de", [1, 1])
        with self.assertRaises(ValueError) as caught:
            parse_level("I would rather not say")

        why = gate(self.root, "de", [2, 2], aborted=str(caught.exception))

        self.assertIn("verification aborted", why)
        self.assertIn("names no level", why)
        self.assertEqual(accepted_levels(self.root), {"de": 1.0})


if __name__ == "__main__":
    unittest.main()
