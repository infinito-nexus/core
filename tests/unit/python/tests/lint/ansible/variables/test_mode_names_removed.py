"""Negative controls for the self-expiring mode-rename guard."""

from __future__ import annotations

import datetime as dt
import unittest

from tests.lint.ansible.variables import test_removed_names

lint = test_removed_names.ModeNames

PREFIX = "MODE_"


class TestNamed(unittest.TestCase):
    def test_every_old_name_is_found(self) -> None:
        for old in lint.RENAMES:
            with self.subTest(old=old):
                self.assertEqual([(2, old)], lint.named(f"---\n{old}: false\n"))

    def test_the_local_variant_is_found_whole(self) -> None:
        old = f"{PREFIX}ASSERT_LOCAL"
        self.assertEqual([(1, old)], lint.named(f"when: {old} | bool\n"))

    def test_an_extra_var_and_a_jinja_read_are_found(self) -> None:
        text = f"-e {PREFIX}DEBUG=true\n{{{{ {PREFIX}DEMO | bool }}}}\n"
        self.assertEqual(
            [(1, f"{PREFIX}DEBUG"), (2, f"{PREFIX}DEMO")], lint.named(text)
        )

    def test_a_longer_name_is_not_found(self) -> None:
        self.assertEqual([], lint.named(f"-e J_{PREFIX}DEBUG=1\n"))
        self.assertEqual([], lint.named(f"{PREFIX}DEBUGGER: 1\n"))

    def test_the_new_names_are_not_found(self) -> None:
        text = "".join(f"{new}: true\n" for new in lint.RENAMES.values())
        self.assertEqual([], lint.named(text))

    def test_every_rename_targets_a_current_mode(self) -> None:
        self.assertEqual(
            {"DUMMY", "DEBUG", "RESET", "CLEANUP", "VALIDATE", "BACKUP", "DEMO"},
            set(lint.RENAMES.values()),
        )


class TestExpiry(unittest.TestCase):
    def test_the_day_before_the_sunset_is_live(self) -> None:
        self.assertFalse(lint.expired(lint.SUNSET - dt.timedelta(days=1)))

    def test_the_sunset_day_expires_the_guard(self) -> None:
        self.assertTrue(lint.expired(lint.SUNSET))

    def test_the_sunset_is_the_agreed_date(self) -> None:
        self.assertEqual(dt.date(2027, 2, 4), lint.SUNSET)


if __name__ == "__main__":
    unittest.main()
