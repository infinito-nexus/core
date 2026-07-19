import unittest

from plugins.filter.ruby import FilterModule


class TestRubyDq(unittest.TestCase):
    """ruby_dq escapes a value for a Ruby double-quoted string and wraps it
    in double quotes; used by the gitlab smtp_settings.rb initializer."""

    def setUp(self):
        self.f = FilterModule().filters()["ruby_dq"]

    def test_none_returns_empty_quotes(self):
        self.assertEqual(self.f(None), '""')

    def test_empty_string(self):
        self.assertEqual(self.f(""), '""')

    def test_plain_value_wrapped(self):
        self.assertEqual(self.f("secret"), '"secret"')

    def test_backslash_escaped(self):
        self.assertEqual(self.f("a\\b"), '"a\\\\b"')

    def test_double_quote_escaped(self):
        self.assertEqual(self.f('a"b'), '"a\\"b"')

    def test_newline_escaped(self):
        self.assertEqual(self.f("a\nb"), '"a\\nb"')

    def test_carriage_return_escaped(self):
        self.assertEqual(self.f("a\rb"), '"a\\rb"')

    def test_tab_escaped(self):
        self.assertEqual(self.f("a\tb"), '"a\\tb"')

    def test_backslash_before_quote_order(self):
        self.assertEqual(self.f('\\"'), '"\\\\\\""')

    def test_dollar_and_single_quote_untouched(self):
        self.assertEqual(self.f("$a'b"), '"$a\'b"')

    def test_non_string_is_stringified(self):
        self.assertEqual(self.f(123), '"123"')


if __name__ == "__main__":
    unittest.main()
