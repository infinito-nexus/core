import unittest

import jinja2

from plugins.filter.dotenv import FilterModule


class TestDotenvQuote(unittest.TestCase):
    """Direct-call behaviour: no Jinja context -> compose-style quoting.

    This path is what unit tests, helper scripts, and any other Python
    caller hit when invoking the filter as a plain function. Preserves
    the pre-mode-aware-split behaviour as a safe default.
    """

    def setUp(self):
        self.f = FilterModule().filters()["dotenv_quote"]

    def test_none(self):
        self.assertEqual(self.f(None), '""')

    def test_empty_string(self):
        self.assertEqual(self.f(""), '""')

    def test_plain_string_is_double_quoted(self):
        self.assertEqual(self.f("abc"), '"abc"')

    def test_single_quote_is_preserved(self):
        self.assertEqual(self.f("'secret"), '"\'secret"')

    def test_dollar_is_escaped_for_compose(self):
        self.assertEqual(self.f("$tr0ng"), '"$$tr0ng"')
        self.assertEqual(self.f("'$tr0ng€xampl3PW!"), '"\'$$tr0ng€xampl3PW!"')

    def test_multiple_dollars(self):
        self.assertEqual(self.f("a$b$c"), '"a$$b$$c"')

    def test_existing_double_dollars_are_doubled_again(self):
        self.assertEqual(self.f("$$FOO"), '"$$$$FOO"')

    def test_backslash_is_escaped(self):
        self.assertEqual(self.f(r"pa\ss"), r'"pa\\ss"')

    def test_double_quote_is_escaped(self):
        self.assertEqual(self.f('pa"ss'), r'"pa\"ss"')

    def test_backslash_and_quote_combination(self):
        self.assertEqual(self.f(r"pa\"ss"), r'"pa\\\"ss"')

    def test_non_string_input_is_stringified(self):
        self.assertEqual(self.f(123), '"123"')
        self.assertEqual(self.f(True), '"True"')

    def test_unicode_is_preserved(self):
        self.assertEqual(self.f("€"), '"€"')
        self.assertEqual(self.f("p€ss$word"), '"p€ss$$word"')


class TestDotenvQuoteModeAware(unittest.TestCase):
    """Through-Jinja behaviour: DEPLOYMENT_MODE in the render context
    switches the filter between compose-style quoting and swarm
    passthrough.

    This is what real env.j2 rendering hits. Without the swarm branch,
    docker stack deploy preserves the literal double quotes and the
    container reads ``KEY="value"`` instead of ``KEY=value``, breaking
    DB auth, URL parsers, and ``int(os.environ['KEY'])``.
    """

    def setUp(self):
        env = jinja2.Environment(autoescape=False)  # noqa: S701 - test renders a .env value, not HTML
        env.filters["dotenv_quote"] = FilterModule().filters()["dotenv_quote"]
        self.env = env

    def _render(self, value, *, mode=None):
        tpl = self.env.from_string("{{ value | dotenv_quote }}")
        ctx = {"value": value}
        if mode is not None:
            ctx["DEPLOYMENT_MODE"] = mode
        return tpl.render(**ctx)

    def test_swarm_returns_value_without_quotes(self):
        self.assertEqual(self._render("plain_secret", mode="swarm"), "plain_secret")

    def test_swarm_does_not_escape_dollars(self):
        self.assertEqual(self._render("$ecre$$t", mode="swarm"), "$ecre$$t")

    def test_swarm_does_not_escape_double_quotes(self):
        self.assertEqual(self._render('pa"ss', mode="swarm"), 'pa"ss')

    def test_swarm_none_returns_empty_string(self):
        self.assertEqual(self._render(None, mode="swarm"), "")

    def test_swarm_non_string_is_stringified(self):
        self.assertEqual(self._render(42, mode="swarm"), "42")

    def test_swarm_quotes_value_with_interior_whitespace(self):
        self.assertEqual(
            self._render("My Org Helpdesk", mode="swarm"), '"My Org Helpdesk"'
        )

    def test_swarm_whitespace_value_escapes_quotes_not_dollars(self):
        self.assertEqual(self._render('a "b" $c', mode="swarm"), '"a \\"b\\" $c"')

    def test_compose_mode_quotes_like_default(self):
        self.assertEqual(self._render("abc", mode="compose"), '"abc"')
        self.assertEqual(self._render("$ecret", mode="compose"), '"$$ecret"')

    def test_unknown_mode_falls_back_to_compose_quoting(self):
        self.assertEqual(self._render("abc", mode="kubernetes"), '"abc"')

    def test_missing_deployment_mode_falls_back_to_compose_quoting(self):
        self.assertEqual(self._render("abc"), '"abc"')


if __name__ == "__main__":
    unittest.main()
