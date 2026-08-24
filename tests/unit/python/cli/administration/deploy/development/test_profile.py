"""Unit tests for Profile."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cli.administration.deploy.development.profile import Profile

_BLANK_CI_ENV = {
    "GITHUB_ACTIONS": "",
    "INFINITO_RUNNING_ON_GITHUB": "",
    "CI": "",
    "INFINITO_INSTANCE": "0",
    "INFINITO_GIT_COMMON_DIR": "",
    "INFINITO_CACHE_NETWORK": "",
    "INFINITO_CACHE_STACK": "",
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


class TestProfileCacheStackEnabled(unittest.TestCase):
    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_active_locally_when_no_ci_signal_set(self) -> None:
        self.assertTrue(Profile().cache_stack_enabled())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "true"}, clear=False)
    def test_inactive_under_github_actions(self) -> None:
        self.assertFalse(Profile().cache_stack_enabled())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_inactive_under_generic_ci_signal(self) -> None:
        self.assertFalse(Profile().cache_stack_enabled())

    @patch.dict(
        os.environ, {**_BLANK_CI_ENV, "INFINITO_RUNNING_ON_GITHUB": "true"}, clear=False
    )
    def test_defaults_to_the_inverse_of_is_ci(self) -> None:
        p = Profile()
        self.assertEqual(p.cache_stack_enabled(), not p.is_ci())


_ON_CI = {**_BLANK_CI_ENV, "GITHUB_ACTIONS": "true"}


class TestProfileDeclaredCapabilities(unittest.TestCase):
    @patch.dict(os.environ, {**_ON_CI, "INFINITO_CACHE_STACK": "true"}, clear=False)
    def test_declaration_wins_over_the_ci_default(self) -> None:
        p = Profile()
        self.assertTrue(p.is_ci())
        self.assertTrue(p.cache_stack_enabled())

    @patch.dict(os.environ, {**_ON_CI, "INFINITO_CACHE_STACK": "yes"}, clear=False)
    def test_a_non_boolean_declaration_falls_back_to_the_default(self) -> None:
        self.assertFalse(Profile().cache_stack_enabled())

    @patch.dict(os.environ, _ON_CI, clear=False)
    def test_act_gets_no_mirrors_and_keeps_its_docker_root(self) -> None:
        p = Profile()
        self.assertTrue(p.is_ci())
        self.assertFalse(p.runs_on_github())
        self.assertFalse(p.cache_stack_enabled())
        self.assertFalse(p.image_mirror_enabled())
        self.assertFalse(p.docker_root_ephemeral())

    @patch.dict(
        os.environ,
        {**_BLANK_CI_ENV, "INFINITO_RUNNING_ON_GITHUB": "true"},
        clear=False,
    )
    def test_a_real_github_runner_mirrors_and_wipes(self) -> None:
        p = Profile()
        self.assertTrue(p.runs_on_github())
        self.assertFalse(p.cache_stack_enabled())
        self.assertTrue(p.image_mirror_enabled())
        self.assertTrue(p.docker_root_ephemeral())


class TestProfileInstance(unittest.TestCase):
    @patch.dict(os.environ, {**_BLANK_CI_ENV, "INFINITO_INSTANCE": ""}, clear=False)
    def test_unset_instance_is_primary(self) -> None:
        self.assertEqual(Profile().instance(), 0)

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "INFINITO_INSTANCE": "7"}, clear=False)
    def test_numeric_instance_is_parsed(self) -> None:
        self.assertEqual(Profile().instance(), 7)

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "INFINITO_INSTANCE": " 3 "}, clear=False)
    def test_surrounding_whitespace_is_tolerated(self) -> None:
        self.assertEqual(Profile().instance(), 3)

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "INFINITO_INSTANCE": "abc"}, clear=False)
    def test_garbage_falls_back_to_primary(self) -> None:
        self.assertEqual(Profile().instance(), 0)


class TestProfileOwnsCacheStack(unittest.TestCase):
    @patch.dict(os.environ, _BLANK_CI_ENV, clear=False)
    def test_owns_the_stack_when_no_network_was_handed_over(self) -> None:
        self.assertTrue(Profile().owns_cache_stack())

    @patch.dict(
        os.environ, {**_BLANK_CI_ENV, "INFINITO_CACHE_NETWORK": "primary_default"}
    )
    def test_shares_instead_of_owning_when_a_network_is_named(self) -> None:
        p = Profile()
        self.assertFalse(p.owns_cache_stack())
        self.assertTrue(p.cache_stack_enabled())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "INFINITO_INSTANCE": "7"}, clear=False)
    def test_a_stray_slot_alone_does_not_give_the_stack_away(self) -> None:
        self.assertTrue(Profile().owns_cache_stack())

    @patch.dict(os.environ, {**_BLANK_CI_ENV, "CI": "true"}, clear=False)
    def test_ci_never_owns_the_stack(self) -> None:
        self.assertFalse(Profile().owns_cache_stack())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
