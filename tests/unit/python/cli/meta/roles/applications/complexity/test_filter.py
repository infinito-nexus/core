from __future__ import annotations

import unittest

from cli.meta.roles.applications.complexity.filter import (
    FilterError,
    compile_predicate,
)

FIELDS = frozenset({"name", "lifecycle", "weight", "variants"})


def _match(expr: str, row: dict) -> bool:
    return compile_predicate(expr, FIELDS)(row)


class TestFilterComparisons(unittest.TestCase):
    def test_numeric_operators(self) -> None:
        self.assertTrue(_match("weight > 5", {"weight": 10}))
        self.assertFalse(_match("weight > 5", {"weight": 5}))
        self.assertTrue(_match("weight >= 5", {"weight": 5}))
        self.assertTrue(_match("weight <= 5", {"weight": 5}))
        self.assertTrue(_match("weight < 5", {"weight": 4}))

    def test_string_equality_is_case_insensitive(self) -> None:
        self.assertTrue(_match("lifecycle == beta", {"lifecycle": "Beta"}))
        self.assertTrue(_match("lifecycle != beta", {"lifecycle": "alpha"}))
        self.assertFalse(_match("lifecycle != beta", {"lifecycle": "beta"}))

    def test_contains_operator(self) -> None:
        self.assertTrue(_match("name %% next", {"name": "web-app-nextcloud"}))
        self.assertFalse(_match("name %% xyz", {"name": "web-app-nextcloud"}))

    def test_bare_word_is_name_substring(self) -> None:
        self.assertTrue(_match("nextcloud", {"name": "web-app-nextcloud"}))
        self.assertFalse(_match("matrix", {"name": "web-app-nextcloud"}))


class TestFilterSets(unittest.TestCase):
    def test_membership_via_contains_and_eq(self) -> None:
        self.assertTrue(_match("lifecycle %% {alpha,pre}", {"lifecycle": "pre"}))
        self.assertTrue(_match("lifecycle == {alpha,pre}", {"lifecycle": "alpha"}))
        self.assertFalse(_match("lifecycle %% {alpha,pre}", {"lifecycle": "beta"}))

    def test_non_membership(self) -> None:
        self.assertTrue(_match("lifecycle != {alpha,pre}", {"lifecycle": "beta"}))
        self.assertFalse(_match("lifecycle != {alpha,pre}", {"lifecycle": "pre"}))

    def test_numeric_set(self) -> None:
        self.assertTrue(_match("variants %% {1,2,3}", {"variants": 2}))
        self.assertFalse(_match("variants %% {1,2,3}", {"variants": 8}))


class TestFilterLogic(unittest.TestCase):
    def test_and_or_not(self) -> None:
        row = {"weight": 10, "lifecycle": "beta"}
        self.assertTrue(_match("weight > 5 and lifecycle == beta", row))
        self.assertFalse(_match("weight > 50 and lifecycle == beta", row))
        self.assertTrue(_match("weight > 50 or lifecycle == beta", row))
        self.assertTrue(_match("not lifecycle == alpha", row))

    def test_xor(self) -> None:
        row = {"weight": 10, "lifecycle": "beta"}
        self.assertFalse(_match("lifecycle == beta xor weight > 5", row))
        self.assertTrue(_match("lifecycle == alpha xor weight > 5", row))

    def test_precedence_and_binds_tighter_than_or(self) -> None:
        row = {"weight": 10, "lifecycle": "beta"}
        self.assertFalse(
            _match("lifecycle == alpha or lifecycle == beta and weight > 50", row)
        )

    def test_parentheses_override_precedence(self) -> None:
        row = {"weight": 10, "lifecycle": "beta"}
        self.assertTrue(
            _match("(lifecycle == alpha or lifecycle == beta) and weight > 5", row)
        )


class TestFilterErrors(unittest.TestCase):
    def test_unknown_field(self) -> None:
        with self.assertRaises(FilterError):
            compile_predicate("bogus == 1", FIELDS)

    def test_missing_value(self) -> None:
        with self.assertRaises(FilterError):
            compile_predicate("weight >", FIELDS)

    def test_trailing_tokens(self) -> None:
        with self.assertRaises(FilterError):
            compile_predicate("weight > 5 5", FIELDS)

    def test_set_with_ordering_operator_rejected(self) -> None:
        with self.assertRaises(FilterError):
            compile_predicate("weight < {1,2}", FIELDS)({"weight": 1})


if __name__ == "__main__":
    unittest.main()
