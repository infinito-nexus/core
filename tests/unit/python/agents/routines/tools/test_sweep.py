"""Unit test: the sweep resumer returns the apps from the last red app onward,
inclusive, in complexity order."""

from __future__ import annotations

import unittest

from agents.routines.tools.sweep import remaining_apps

_ORDER = ["static", "blog", "cloud", "chat", "ai"]


class TestRemainingApps(unittest.TestCase):
    def test_resumes_inclusive_from_last_red(self) -> None:
        self.assertEqual(remaining_apps(_ORDER, "cloud"), ["cloud", "chat", "ai"])

    def test_first_app(self) -> None:
        self.assertEqual(remaining_apps(_ORDER, "static"), _ORDER)

    def test_last_app(self) -> None:
        self.assertEqual(remaining_apps(_ORDER, "ai"), ["ai"])

    def test_unknown_app_raises(self) -> None:
        with self.assertRaises(ValueError):
            remaining_apps(_ORDER, "missing")


if __name__ == "__main__":
    unittest.main()
