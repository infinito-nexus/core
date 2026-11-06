"""Unit test: the hang watchdog takes its silence threshold from the onion
Playwright budget of the Playwright role's vars, so the silences healthy
deploys showed (a Playwright container run, a rebuild handler) are no hang; it
measures silence not total runtime, takes its threshold from every caller, and
reads the CPU ticks of a live process tree."""

from __future__ import annotations

import inspect
import os
import unittest

from agents.routines.tools.watchdog import (
    _PLAYWRIGHT_VARS,
    SILENCE_SECONDS,
    is_hung,
    process_ticks,
)
from utils.cache.yaml import load_yaml

_NOW = 100_000.0
_HEALTHY_SILENCES = (948.0, 1126.0)


class TestWatchdog(unittest.TestCase):
    def test_the_threshold_covers_the_onion_playwright_run_timeout(self) -> None:
        values = load_yaml(_PLAYWRIGHT_VARS)
        self.assertGreater(
            SILENCE_SECONDS, values["TEST_E2E_PLAYWRIGHT_ONION_RUN_TIMEOUT"]
        )

    def test_healthy_silences_are_no_hang(self) -> None:
        for silence in _HEALTHY_SILENCES:
            with self.subTest(silence=silence):
                self.assertFalse(is_hung([_NOW - silence], _NOW, SILENCE_SECONDS))

    def test_the_threshold_has_no_default(self) -> None:
        silence = inspect.signature(is_hung).parameters["silence"]
        self.assertIs(silence.default, inspect.Parameter.empty)

    def test_fires_after_silence(self) -> None:
        self.assertTrue(is_hung([_NOW - SILENCE_SECONDS - 1], _NOW, SILENCE_SECONDS))

    def test_quiet_on_long_run_with_recent_output(self) -> None:
        self.assertFalse(is_hung([1_000.0, 5_000.0, _NOW - 50], _NOW, SILENCE_SECONDS))

    def test_exact_threshold_does_not_fire(self) -> None:
        self.assertFalse(is_hung([_NOW - SILENCE_SECONDS], _NOW, SILENCE_SECONDS))

    def test_custom_threshold(self) -> None:
        self.assertTrue(is_hung([_NOW - 120.0], _NOW, 60.0))

    def test_no_output_is_not_hung(self) -> None:
        self.assertFalse(is_hung([], _NOW, SILENCE_SECONDS))


class TestProcessTicks(unittest.TestCase):
    def test_a_live_process_has_ticks(self) -> None:
        self.assertIsInstance(process_ticks(os.getpid()), int)

    def test_a_gone_process_has_none(self) -> None:
        self.assertIsNone(process_ticks(0))


if __name__ == "__main__":
    unittest.main()
