import unittest

import jinja2

from plugins.filter.dotenv import FilterModule


class TestDotenvValue(unittest.TestCase):
    """Reading one assignment back out of a rendered .env."""

    def setUp(self):
        self.f = FilterModule().filters()["dotenv_value"]

    def test_returns_the_right_hand_side_still_quoted(self):
        env = 'A=1\nKEY="se cret"\nB=2\n'
        self.assertEqual(self.f(env, "KEY"), '"se cret"')

    def test_absent_key_is_empty(self):
        self.assertEqual(self.f("A=1\n", "KEY"), "")

    def test_a_longer_key_with_the_same_prefix_does_not_match(self):
        self.assertEqual(self.f("KEY_EXTRA=1\n", "KEY"), "")

    def test_empty_content_is_empty(self):
        self.assertEqual(self.f("", "KEY"), "")
        self.assertEqual(self.f(None, "KEY"), "")


class TestDotenvUnquoteRoundTrip(unittest.TestCase):
    """Whatever dotenv_quote writes, dotenv_unquote must read back."""

    def setUp(self):
        filters = FilterModule().filters()
        self.quote = filters["dotenv_quote"]
        self.unquote = filters["dotenv_unquote"]

    def test_round_trip_without_a_context(self):
        for value in ("abc", "p$w", "back\\slash", 'quote"inside', "", "a$$b"):
            with self.subTest(value=value):
                self.assertEqual(self.unquote(self.quote(value)), value)

    def test_none_round_trips_to_empty(self):
        self.assertEqual(self.unquote(self.quote(None)), "")


class TestDotenvUnquoteModeAware(unittest.TestCase):
    """Swarm writes the value verbatim, so reading it back must not unescape."""

    def setUp(self):
        env = jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False)
        )
        filters = FilterModule().filters()
        env.filters["dotenv_quote"] = filters["dotenv_quote"]
        env.filters["dotenv_unquote"] = filters["dotenv_unquote"]
        self.env = env

    def _round_trip(self, value, *, mode):
        tpl = self.env.from_string("{{ value | dotenv_quote | dotenv_unquote }}")
        return tpl.render(value=value, DEPLOYMENT_MODE=mode)

    def test_swarm_round_trips_a_dollar_verbatim(self):
        self.assertEqual(self._round_trip("$ecre$$t", mode="swarm"), "$ecre$$t")

    def test_swarm_round_trips_a_double_quote_verbatim(self):
        self.assertEqual(self._round_trip('pa"ss', mode="swarm"), 'pa"ss')

    def test_compose_round_trips_the_same_values(self):
        self.assertEqual(self._round_trip("$ecre$$t", mode="compose"), "$ecre$$t")
        self.assertEqual(self._round_trip('pa"ss', mode="compose"), 'pa"ss')


if __name__ == "__main__":
    unittest.main()
