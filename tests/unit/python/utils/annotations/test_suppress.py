"""Unit tests for the unified suppression-marker grammar."""

from __future__ import annotations

import unittest

from utils.annotations.suppress import (
    is_suppressed_anywhere,
    is_suppressed_at,
    is_suppressed_in_head,
    line_has_rule,
    suppressed_line_numbers,
)


class TestLineHasRule(unittest.TestCase):
    def test_noqa_and_nocheck_are_synonyms(self):
        self.assertTrue(line_has_rule("# noqa: url", "url"))
        self.assertTrue(line_has_rule("# nocheck: url", "url"))

    def test_case_insensitive(self):
        self.assertTrue(line_has_rule("# NOQA: URL", "url"))
        self.assertTrue(line_has_rule("# NoCheck: Url", "url"))

    def test_html_jinja_and_slash_prefixes(self):
        self.assertTrue(line_has_rule("<!-- nocheck: url -->", "url"))
        self.assertTrue(line_has_rule("{# nocheck: url #}", "url"))
        self.assertTrue(line_has_rule("// noqa: url", "url"))

    def test_inline_marker_in_code(self):
        line = 'tokens.append("https://example.org")  # nocheck: url'
        self.assertTrue(line_has_rule(line, "url"))

    def test_multi_rule_comma_separated(self):
        line = "# noqa: shared, email"
        self.assertTrue(line_has_rule(line, "shared"))
        self.assertTrue(line_has_rule(line, "email"))
        self.assertFalse(line_has_rule(line, "url"))

    def test_unrelated_text_does_not_match(self):
        self.assertFalse(line_has_rule("# this is just a comment", "url"))
        self.assertFalse(line_has_rule("noqa url", "url"))  # missing colon

    def test_word_boundary_avoids_false_positives(self):
        self.assertFalse(line_has_rule("# nocheck: url-other", "url"))
        self.assertTrue(line_has_rule("# nocheck: url-other", "url-other"))


class TestIsSuppressedAt(unittest.TestCase):
    def test_same_line_mode(self):
        lines = ["x = 1", "y = 2  # nocheck: url"]
        self.assertTrue(is_suppressed_at(lines, 2, "url", mode="same-line"))
        self.assertFalse(is_suppressed_at(lines, 1, "url", mode="same-line"))

    def test_line_above_mode(self):
        lines = ["# nocheck: docker-version", "version: 1.2.3"]
        self.assertTrue(is_suppressed_at(lines, 2, "docker-version", mode="line-above"))
        self.assertFalse(is_suppressed_at(lines, 2, "docker-version", mode="same-line"))

    def test_line_above_skips_blank_lines(self):
        lines = ["# noqa: email", "", "", "email:"]
        self.assertTrue(is_suppressed_at(lines, 4, "email", mode="line-above"))

    def test_default_mode_accepts_either(self):
        same = ["foo  # nocheck: url"]
        above = ["# nocheck: url", "foo"]
        self.assertTrue(is_suppressed_at(same, 1, "url"))
        self.assertTrue(is_suppressed_at(above, 2, "url"))

    def test_out_of_range_returns_false(self):
        self.assertFalse(is_suppressed_at([], 1, "url"))
        self.assertFalse(is_suppressed_at(["x"], 0, "url"))
        self.assertFalse(is_suppressed_at(["x"], 999, "url"))


class TestFileLevelHelpers(unittest.TestCase):
    def test_head_marker_within_scan_window(self):
        lines = ['"""docstring."""', "# nocheck: file-size", "rest = 1"]
        self.assertTrue(is_suppressed_in_head(lines, "file-size", scan_lines=30))

    def test_head_marker_outside_scan_window_misses(self):
        lines = ["x = 1"] * 40 + ["# nocheck: file-size"]
        self.assertFalse(is_suppressed_in_head(lines, "file-size", scan_lines=30))

    def test_anywhere_marker(self):
        lines = ["x = 1"] * 100 + ["# nocheck: run-once"]
        self.assertTrue(is_suppressed_anywhere(lines, "run-once"))

    def test_anywhere_no_match(self):
        self.assertFalse(is_suppressed_anywhere(["x", "y"], "run-once"))


class TestSuppressedLineNumbers(unittest.TestCase):
    def test_returns_one_based_line_numbers(self):
        lines = [
            "# unrelated",
            "# noqa: url",
            "x  # nocheck: url",
            "# noqa: shared",
        ]
        self.assertEqual(suppressed_line_numbers(lines, "url"), {2, 3})
        self.assertEqual(suppressed_line_numbers(lines, "shared"), {4})


if __name__ == "__main__":
    unittest.main()
