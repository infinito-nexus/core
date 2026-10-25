"""Unit test: the environment-key plan runs the key once true and once false."""

from __future__ import annotations

import unittest

from agents.routines.tools.env_key import both_value_runs


class TestEnvKey(unittest.TestCase):
    def test_two_runs_true_then_false(self) -> None:
        self.assertEqual(
            both_value_runs("ASYNC_ENABLED"),
            [
                {"key": "ASYNC_ENABLED", "value": "true"},
                {"key": "ASYNC_ENABLED", "value": "false"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
