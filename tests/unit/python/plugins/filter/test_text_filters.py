import json
import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.text_filters import to_inline_js, to_one_liner

HOSTILE = {"text": ']=] /*x*/ </script> // a=b "q" \\ ü'}
SPACED = {
    "text": "two  spaces,   three and a trailing ",
    "key with  space": [" a", "b  "],
}


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

    def test_inline_js_round_trips_as_json(self):
        self.assertEqual(json.loads(to_inline_js(HOSTILE)), HOSTILE)

    def test_inline_js_hides_every_breakout_sequence(self):
        literal = to_inline_js(HOSTILE)
        for sequence in ("]=]", "</", "/*", "*/", "//", "<", "="):
            self.assertNotIn(sequence, literal)

    def test_inline_js_survives_the_one_liner(self):
        script = f"const value = {to_inline_js(HOSTILE)};"
        self.assertEqual(to_one_liner(script), script)

    def test_inline_js_keeps_a_run_of_spaces_through_the_one_liner(self):
        script = to_one_liner(f"const value = {to_inline_js(SPACED)};")
        literal = script.removeprefix("const value = ").removesuffix(";")
        self.assertEqual(json.loads(literal), SPACED)

    def test_inline_js_writes_no_raw_space(self):
        self.assertNotIn(" ", to_inline_js(SPACED))

    def test_inline_js_rejects_what_json_cannot_hold(self):
        with self.assertRaises(AnsibleFilterError):
            to_inline_js({"value": object()})


if __name__ == "__main__":
    unittest.main()
