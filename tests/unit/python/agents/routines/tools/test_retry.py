"""Unit test: a flaky failure is retried once; a deterministic one is not."""

from __future__ import annotations

import unittest

from agents.routines.tools.retry import should_retry


class TestRetry(unittest.TestCase):
    def test_flaky_is_retried(self) -> None:
        self.assertTrue(should_retry("flaky"))
        self.assertTrue(should_retry("  Flaky  "))

    def test_deterministic_is_not_retried(self) -> None:
        self.assertFalse(should_retry("deterministic"))
        self.assertFalse(should_retry("infra race"))


if __name__ == "__main__":
    unittest.main()
