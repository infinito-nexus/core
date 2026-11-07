"""Unit test: the environment-key plan runs the key once true and once false,
and a test that does not clear the key fails one of the two runs."""

from __future__ import annotations

import unittest

from agents.routines.tools.env_key import both_value_runs, leaks, run_both

_KEY = "FIXTURE_FEATURE_FLAG"


def _feature_enabled(env) -> bool:
    return env.get(_KEY) == "true"


def leaky_suite(env) -> bool:
    """A suite whose test asserts the default without clearing the key."""
    return _feature_enabled(env) is False


def clean_suite(env) -> bool:
    """The same test, which clears the key before it asserts the default."""
    cleared = {name: value for name, value in env.items() if name != _KEY}
    return _feature_enabled(cleared) is False


class TestEnvKey(unittest.TestCase):
    def test_two_runs_true_then_false(self) -> None:
        self.assertEqual(
            both_value_runs("DEBUG"),
            [
                {"key": "DEBUG", "value": "true"},
                {"key": "DEBUG", "value": "false"},
            ],
        )

    def test_a_test_that_does_not_clear_the_key_fails_one_run(self) -> None:
        outcomes = run_both(_KEY, leaky_suite, {"PATH": "/usr/bin"})
        self.assertEqual(outcomes, {"true": False, "false": True})
        self.assertTrue(leaks(outcomes))

    def test_a_test_that_clears_the_key_passes_both_runs(self) -> None:
        outcomes = run_both(_KEY, clean_suite, {"PATH": "/usr/bin"})
        self.assertEqual(outcomes, {"true": True, "false": True})
        self.assertFalse(leaks(outcomes))

    def test_each_run_gets_its_own_environment(self) -> None:
        base = {"PATH": "/usr/bin"}
        seen: list[str] = []
        run_both(_KEY, lambda env: seen.append(env[_KEY]) is None, base)
        self.assertEqual(seen, ["true", "false"])
        self.assertNotIn(_KEY, base)


if __name__ == "__main__":
    unittest.main()
