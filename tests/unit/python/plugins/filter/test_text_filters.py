import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.text_filters import to_one_liner


class TestTextFilters(unittest.TestCase):
    def test_collapse_whitespace(self):
        s = """Line one

    Line   two
Line three"""
        expected = "Line one Line two Line three"
        self.assertEqual(to_one_liner(s), expected)

    def test_remove_js_line_comments(self):
        s = "var a = 1; // this is a comment\nvar b = 2;"
        expected = "var a = 1; var b = 2;"
        self.assertEqual(to_one_liner(s), expected)

    def test_remove_js_block_comments(self):
        s = "var a = /* comment inside */ 1; var b = 2;"
        expected = "var a = 1; var b = 2;"
        self.assertEqual(to_one_liner(s), expected)

    def test_remove_multiple_comments(self):
        s = "// first comment\nvar a = 1; /* block comment */ var b = 2; // end comment"
        expected = "var a = 1; var b = 2;"
        self.assertEqual(to_one_liner(s), expected)

    def test_strips_leading_trailing_whitespace(self):
        s = "   \n   some text here   \n   "
        expected = "some text here"
        self.assertEqual(to_one_liner(s), expected)

    def test_non_string_raises(self):
        with self.assertRaises(AnsibleFilterError):
            to_one_liner(123)

    def test_preserve_urls_in_string_literals(self):
        s = 'var url = "http://example.com/path"; // comment'
        expected = 'var url = "http://example.com/path";'
        self.assertEqual(to_one_liner(s), expected)

    def test_preserve_escaped_quotes_and_protocol(self):
        s = "var s = 'He said \\'//not comment\\''; // remove this"
        expected = "var s = 'He said \\'//not comment\\'';"
        self.assertEqual(to_one_liner(s), expected)

    def test_preserve_templating_expressions(self):
        s = "var tracker = \"//{{ domains | get_domain('web-app-matomo') }}/matomo.js\"; // loader"
        expected = "var tracker = \"//{{ domains | get_domain('web-app-matomo') }}/matomo.js\";"
        self.assertEqual(to_one_liner(s), expected)

    def test_mixed_string_and_comment(self):
        s = """
            var a = "foo // still part of string";
            // top-level comment
            var b = 2; // end comment
        """
        expected = 'var a = "foo // still part of string"; var b = 2;'
        self.assertEqual(to_one_liner(s), expected)


if __name__ == "__main__":
    unittest.main()
