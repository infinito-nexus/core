"""Unit tests for Profile."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cli.administration.deploy.development.profile import Profile

# Blank explicit signals; clear=True would unset PATH.
_BLANK_CI_ENV = {
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "CI": "",
}


class TestProfileIsCI(unittest.TestCase):
    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_is_ci_false_when_no_signals_set(self) -> None:
        self.assertFalse(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "true"}, clear=False)
    def test_is_ci_true_when_github_actions_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(
        os.environ, {**_BLANK_CI_ENV, "INFINITO_RUNNING_ON_GITHUB": "true"}, clear=False
    )
    def test_is_ci_true_when_running_on_github_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_is_ci_true_when_generic_ci_signal_set(self) -> None:
        self.assertTrue(Profile().is_ci())

    @patch.dict(
        os.environ,
        {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "1"},
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

    @patch.dict(
        os.environ, {**_BLANK_CI_ENV, "INFINITO_RUNNING_ON_GITHUB": "true"}, clear=False
    )
    def test_is_strict_inverse_of_is_ci(self) -> None:
        p = Profile()
        self.assertEqual(p.registry_cache_active(), not p.is_ci())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
