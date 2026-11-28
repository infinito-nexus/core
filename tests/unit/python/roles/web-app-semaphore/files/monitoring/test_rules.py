from __future__ import annotations

import unittest
import unittest.mock as mock

from ._fake_monitoring import rules


class TestTheRuleValue(unittest.TestCase):
    def test_an_oversized_value_is_unreadable_even_when_it_parses(self) -> None:
        padded = repr({}) + " " * rules.VALUE_RAW_LIMIT
        self.assertEqual(rules.rule_value({"extensions": {"value_raw": "{}"}}), {})
        self.assertIsNone(rules.rule_value({"extensions": {"value_raw": padded}}))

    def test_a_value_the_parser_chokes_on_is_unreadable(self) -> None:
        for error in (TypeError, MemoryError, RecursionError, SyntaxError, ValueError):
            with (
                self.subTest(error=error.__name__),
                mock.patch.object(rules.ast, "literal_eval", side_effect=error),
            ):
                self.assertIsNone(rules.rule_value({"extensions": {"value_raw": "{}"}}))
        self.assertIsNone(rules.rule_value({"extensions": {"value_raw": 7}}))


if __name__ == "__main__":
    unittest.main()
