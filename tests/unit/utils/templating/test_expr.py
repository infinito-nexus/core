# Ensure repo root is importable so `utils.*` resolves in all runners
import sys
import unittest

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from utils.templating.expr import (
    find_top_level_op,
    is_paren_wrapped,
    split_list_items,
    split_top_level,
)


class TestSplitListItems(unittest.TestCase):
    def test_bare_and_quoted_tokens(self):
        self.assertEqual(
            split_list_items("DIR_BIN, 'ca-inject'"), ["DIR_BIN", "'ca-inject'"]
        )

    def test_comma_inside_quotes_is_not_a_separator(self):
        self.assertEqual(split_list_items("'a,b', c"), ["'a,b'", "c"])

    def test_mixed_quote_styles(self):
        self.assertEqual(split_list_items("\"x\", 'y'"), ['"x"', "'y'"])

    def test_empty_and_whitespace_tokens_dropped(self):
        self.assertEqual(split_list_items(" a ,, b , "), ["a", "b"])

    def test_empty_string(self):
        self.assertEqual(split_list_items(""), [])


class TestFindTopLevelOp(unittest.TestCase):
    def test_finds_operator_at_depth_zero(self):
        self.assertEqual(find_top_level_op("A == B", "=="), 2)

    def test_skips_operator_inside_parens(self):
        expr = "(A == B) != C"
        self.assertEqual(find_top_level_op(expr, "!="), expr.index("!="))
        self.assertEqual(find_top_level_op("(A == B)", "=="), -1)

    def test_skips_operator_inside_quotes(self):
        expr = "'x == y' == Z"
        self.assertEqual(find_top_level_op(expr, "=="), 9)

    def test_word_operator_padded_with_spaces(self):
        # " if " must not match inside identifiers like "notify".
        self.assertEqual(find_top_level_op("gift if COND else b", " if "), 4)
        self.assertEqual(find_top_level_op("gifted", " if "), -1)

    def test_not_found(self):
        self.assertEqual(find_top_level_op("A ~ B", "=="), -1)

    def test_bracket_kinds_all_count_as_depth(self):
        self.assertEqual(find_top_level_op("[a == b] == c", "=="), 9)
        self.assertEqual(find_top_level_op("{a == b} == c", "=="), 9)


class TestSplitTopLevel(unittest.TestCase):
    def test_simple_split(self):
        self.assertEqual(split_top_level("a ~ b ~ c", "~"), ["a ", " b ", " c"])

    def test_separator_inside_quotes_kept(self):
        self.assertEqual(split_top_level("'a ~ b' ~ c", "~"), ["'a ~ b' ", " c"])

    def test_separator_inside_parens_kept(self):
        self.assertEqual(split_top_level("(a ~ b) ~ c", "~"), ["(a ~ b) ", " c"])

    def test_no_separator_returns_whole(self):
        self.assertEqual(split_top_level("abc", "~"), ["abc"])


class TestIsParenWrapped(unittest.TestCase):
    def test_fully_wrapped(self):
        self.assertTrue(is_paren_wrapped("(a ~ b)"))

    def test_adjacent_groups_are_not_wrapped(self):
        self.assertFalse(is_paren_wrapped("(a) ~ (b)"))

    def test_no_parens(self):
        self.assertFalse(is_paren_wrapped("a ~ b"))

    def test_nested_wrap(self):
        self.assertTrue(is_paren_wrapped("((a) ~ (b))"))

    def test_close_paren_inside_quotes_ignored(self):
        self.assertTrue(is_paren_wrapped("(a ~ ')' ~ b)"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
