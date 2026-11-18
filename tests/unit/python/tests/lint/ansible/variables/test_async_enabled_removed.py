"""Negative controls for the self-expiring removal guard."""

from __future__ import annotations

import datetime as dt
import unittest

from tests.lint.ansible.variables import test_removed_names

lint = test_removed_names.AsyncEnabled


class TestNamedLines(unittest.TestCase):
    def test_a_group_var_is_found(self) -> None:
        self.assertEqual([2], lint.named_lines(f"---\n{lint.NAME}: false\n"))

    def test_an_extra_var_is_found(self) -> None:
        self.assertEqual([1], lint.named_lines(f"-e {lint.NAME}=true\n"))

    def test_a_jinja_read_is_found(self) -> None:
        text = f'async: "{{{{ ASYNC_TIME if {lint.NAME} | bool else omit }}}}"\n'
        self.assertEqual([1], lint.named_lines(text))

    def test_a_longer_name_is_not_found(self) -> None:
        self.assertEqual([], lint.named_lines(f"hetzner_{lint.NAME.lower()}: x\n"))
        self.assertEqual([], lint.named_lines(f"X_{lint.NAME}_Y: 1\n"))

    def test_the_constants_that_stay_are_not_found(self) -> None:
        self.assertEqual([], lint.named_lines("ASYNC_TIME: 300\nASYNC_POLL: 0\n"))


class TestExpiry(unittest.TestCase):
    def test_the_day_before_the_sunset_is_live(self) -> None:
        self.assertFalse(lint.expired(lint.SUNSET - dt.timedelta(days=1)))

    def test_the_sunset_day_expires_the_guard(self) -> None:
        self.assertTrue(lint.expired(lint.SUNSET))

    def test_the_sunset_is_the_agreed_date(self) -> None:
        self.assertEqual(dt.date(2027, 2, 3), lint.SUNSET)


if __name__ == "__main__":
    unittest.main()
