from __future__ import annotations

import unittest

from utils.roles.description import MAX_LENGTH, violations


class TestDescriptionViolations(unittest.TestCase):
    def test_a_noun_phrase_within_the_limit_conforms(self):
        self.assertEqual([], violations("Self-hosted note taking web application"))

    def test_a_text_over_the_limit_is_reported(self):
        self.assertEqual(
            [f"{MAX_LENGTH + 1}>{MAX_LENGTH} chars"], violations("x" * (MAX_LENGTH + 1))
        )

    def test_a_text_at_the_limit_conforms(self):
        self.assertEqual([], violations("x" * MAX_LENGTH))

    def test_a_trailing_period_is_reported(self):
        self.assertEqual(["trailing period"], violations("Note app."))

    def test_a_leading_verb_is_reported_case_insensitively(self):
        self.assertEqual(
            ["starts with verb 'deploys'"], violations("Deploys a note app")
        )

    def test_an_empty_text_conforms(self):
        self.assertEqual([], violations(""))


if __name__ == "__main__":
    unittest.main()
