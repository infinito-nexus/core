"""Unit tests for cli.deploy.development.profile.Profile.

Covers the three public methods (`is_ci`, `registry_cache_active`,
`args`) in isolation, with each case patching `os.environ` so the
host environment cannot leak into the assertions.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cli.deploy.development.profile import Profile


# Reset every CI signal Profile reads. Individual tests overlay the
# specific signal they want active. ``clear=True`` is too aggressive —
# it would unset PATH and break import-time machinery — so blank the
# signals explicitly instead.
_BLANK_CI_ENV = {
    "GITHUB_ACTIONS": "",
    "RUNNING_ON_GITHUB": "",
    "CI": "",
}


class TestProfileIsCI(unittest.TestCase):
    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_is_ci_false_when_no_signals_set(self) -> None:
        self.assertFalse(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "true"}, clear=False)
    def test_is_ci_true_when_github_actions_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "RUNNING_ON_GITHUB": "true"}, clear=False)
    def test_is_ci_true_when_running_on_github_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_is_ci_true_when_generic_ci_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(
        os.environ,
        {
            **_BLANK_CI_ENV,
            # Match has to be exactly the literal "true" — Profile is
            # conservative on purpose so a leftover "1" / "false" /
            # "yes" / quoted-empty value cannot accidentally flip the
            # CI gate. Each variant gets its own assertion below to
            # make the contract explicit.
            "GITHUB_ACTIONS": "1",
        },
        clear=False,
    )
    def test_is_ci_false_when_signal_value_is_one(self) -> None:
        self.assertFalse(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "false"}, clear=False)
    def test_is_ci_false_when_signal_value_is_explicit_false(self) -> None:
        self.assertFalse(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "yes"}, clear=False)
    def test_is_ci_false_when_signal_value_is_yes(self) -> None:
        self.assertFalse(Profile().is_ci())


class TestProfileRegistryCacheActive(unittest.TestCase):
    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_active_locally_when_no_ci_signal_set(self) -> None:
        self.assertTrue(Profile().registry_cache_active())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "true"}, clear=False)
    def test_inactive_under_github_actions(self) -> None:
        self.assertFalse(Profile().registry_cache_active())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_inactive_under_generic_ci_signal(self) -> None:
        self.assertFalse(Profile().registry_cache_active())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "RUNNING_ON_GITHUB": "true"}, clear=False)
    def test_is_strict_inverse_of_is_ci(self) -> None:
        # Sanity check the documented contract: registry_cache_active
        # is the negation of is_ci, no other inputs influence it.
        p = Profile()
        self.assertEqual(p.registry_cache_active(), not p.is_ci())


class TestProfileArgs(unittest.TestCase):
    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_args_ci_only_on_runner(self) -> None:
        # On CI the cache profile stays inactive (fresh disk per job
        # gives no cross-run amortization) so docker compose only sees
        # the ci profile.
        self.assertEqual(Profile().args(), ["--profile", "ci"])

    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_args_includes_cache_profile_locally(self) -> None:
        # Locally the cache profile activates so the registry-cache
        # joins the stack and infinito's depends_on gates it via
        # service_healthy.
        self.assertEqual(
            Profile().args(),
            ["--profile", "ci", "--profile", "cache"],
        )

    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_args_returns_a_fresh_list_each_call(self) -> None:
        # Callers may mutate the returned list (e.g. append further
        # docker compose flags). Two calls must not share state.
        p = Profile()
        first = p.args()
        first.append("--mutated")
        self.assertNotIn("--mutated", p.args())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
