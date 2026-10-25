"""Unit test: the hang watchdog fires on 15 minutes of silence and stays quiet
for a long run that keeps writing output, proving it measures silence not total
runtime."""

from __future__ import annotations

import unittest

from agents.routines.tools.watchdog import is_hung

_NOW = 10_000.0


class TestWatchdog(unittest.TestCase):
    def test_fires_after_silence(self) -> None:
        self.assertTrue(is_hung([8_000.0, 9_000.0], _NOW))

    def test_quiet_on_long_run_with_recent_output(self) -> None:
        self.assertFalse(is_hung([1_000.0, 5_000.0, 9_950.0], _NOW))

    def test_exact_threshold_does_not_fire(self) -> None:
        self.assertFalse(is_hung([_NOW - 900.0], _NOW))

    def test_custom_threshold(self) -> None:
        self.assertTrue(is_hung([_NOW - 120.0], _NOW, silence=60.0))

    def test_no_output_is_not_hung(self) -> None:
        self.assertFalse(is_hung([], _NOW))


if __name__ == "__main__":
    unittest.main()
