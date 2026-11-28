"""Unit test: the negative control passes only when the guarded input turned the
spec red and restoring it turned the spec green."""

from __future__ import annotations

import unittest

from agents.routines.tools.negative_control import control_result


class TestControlResult(unittest.TestCase):
    def test_passes_on_red_then_green(self) -> None:
        self.assertTrue(control_result(before_red=True, after_green=True))

    def test_fails_when_break_stayed_green(self) -> None:
        self.assertFalse(control_result(before_red=False, after_green=True))

    def test_fails_when_restore_stayed_red(self) -> None:
        self.assertFalse(control_result(before_red=True, after_green=False))

    def test_fails_when_neither_held(self) -> None:
        self.assertFalse(control_result(before_red=False, after_green=False))


if __name__ == "__main__":
    unittest.main()
