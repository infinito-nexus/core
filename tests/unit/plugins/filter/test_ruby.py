import unittest

from plugins.filter.ruby import FilterModule


class TestRubySingleLine(unittest.TestCase):
    """ruby_single_line collapses a multi-line Ruby program to one physical
    line so a swarm `docker stack deploy` env-file (which reads embedded
    newlines as separate, whitespace-named entries) keeps a value like
    GITLAB_OMNIBUS_CONFIG intact: statement-boundary newlines (bracket depth 0)
    become ';', newlines inside an open bracket or a string become a space.
    """

    def setUp(self):
        self.f = FilterModule().filters()["ruby_single_line"]

    def test_none_returns_empty(self):
        self.assertEqual(self.f(None), "")

    def test_single_line_unchanged(self):
        self.assertEqual(self.f("a = 1"), "a = 1")

    def test_depth_zero_newline_becomes_semicolon(self):
        self.assertEqual(self.f("a = 1\nb = 2"), "a = 1;b = 2")

    def test_newline_inside_parens_becomes_space(self):
        self.assertEqual(self.f("foo(\na\n)"), "foo( a )")

    def test_newline_inside_brackets_becomes_space(self):
        self.assertEqual(self.f("x = [\n1\n]"), "x = [ 1 ]")

    def test_newline_inside_braces_becomes_space(self):
        self.assertEqual(self.f("h = {\n}"), "h = { }")

    def test_newline_inside_string_becomes_space(self):
        self.assertEqual(self.f("x = 'a\nb'"), "x = 'a b'")

    def test_escaped_quote_in_string_does_not_break_depth(self):
        # backslash + next char pass through verbatim, so the escaped quote
        # does not terminate the string and the following newline is still a
        # depth-0 statement boundary.
        self.assertEqual(self.f('a = "x\\"y"\nb = 2'), 'a = "x\\"y";b = 2')

    def test_realistic_gitlab_omnibus_config(self):
        src = (
            "external_url 'https://gitlab.example'\ngitlab_rails['smtp_enable'] = true"
        )
        self.assertEqual(
            self.f(src),
            "external_url 'https://gitlab.example';gitlab_rails['smtp_enable'] = true",
        )

    def test_non_string_is_stringified(self):
        self.assertEqual(self.f(123), "123")


if __name__ == "__main__":
    unittest.main()
