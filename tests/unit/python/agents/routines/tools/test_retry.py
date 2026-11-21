"""Unit test: a flaky failure is retried once; a deterministic one is not."""

from __future__ import annotations

import unittest

from agents.routines.tools.retry import should_retry


class TestRetry(unittest.TestCase):
    def test_flaky_is_retried(self) -> None:
        self.assertTrue(should_retry("flaky", retries_done=0))
        self.assertTrue(should_retry("  Flaky  ", retries_done=0))

    def test_flaky_is_retried_only_once(self) -> None:
        self.assertFalse(should_retry("flaky", retries_done=1))
        self.assertFalse(should_retry("flaky", retries_done=2))

    def test_deterministic_is_not_retried(self) -> None:
        self.assertFalse(should_retry("deterministic", retries_done=0))
        self.assertFalse(should_retry("infra race", retries_done=0))


if __name__ == "__main__":
    unittest.main()
