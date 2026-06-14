"""Unit tests for the compose_restart lookup plugin.

Pins the contract for the lookup that gates `restart:` emission in
docker-compose templates between compose and swarm deployment modes.

The lookup takes at most one positional argument. With no argument it
falls back to the ansible-vars `DOCKER_RESTART_POLICY` constant (which
is always defined in `group_vars/all/00_general.yml`). With an
argument the caller's resolved value is used verbatim — this is the
path that lets a Jinja-scope
``{% set docker_restart_policy = '...' %}`` override take effect
(the Jinja expression is evaluated in the caller's template, then the
literal result is passed to the lookup).
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_compose_restart",
        str(PROJECT_ROOT / "plugins/lookup/compose_restart.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.LookupModule


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class TestComposeRestartLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _make(self, variables):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def test_no_arg_falls_back_to_docker_restart_policy_constant(self):
        vars_ = {"DEPLOYMENT_MODE": "compose", "DOCKER_RESTART_POLICY": "always"}
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, ["restart: always"])

    def test_no_arg_with_no_constant_uses_unless_stopped_default(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, ["restart: unless-stopped"])

    def test_explicit_arg_wins_over_constant(self):
        vars_ = {"DEPLOYMENT_MODE": "compose", "DOCKER_RESTART_POLICY": "always"}
        lm = self._make(vars_)
        result = lm.run(["on-failure"], variables=vars_)
        self.assertEqual(result, ["restart: on-failure"])

    def test_explicit_arg_no_policy(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run(["no"], variables=vars_)
        self.assertEqual(result, ["restart: no"])

    def test_swarm_mode_emits_empty_no_arg(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm", "DOCKER_RESTART_POLICY": "always"}
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, [""])

    def test_swarm_mode_emits_empty_with_explicit_arg(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        for policy in ("no", "always", "on-failure", "unless-stopped"):
            with self.subTest(policy=policy):
                self.assertEqual(lm.run([policy], variables=vars_), [""])

    def test_swarm_mode_with_surrounding_whitespace(self):
        vars_ = {"DEPLOYMENT_MODE": "  swarm  "}
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, [""])

    def test_missing_deployment_mode_defaults_to_compose(self):
        vars_ = {"DOCKER_RESTART_POLICY": "always"}
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, ["restart: always"])

    def test_none_terms_treated_as_no_args(self):
        vars_ = {"DEPLOYMENT_MODE": "compose", "DOCKER_RESTART_POLICY": "always"}
        lm = self._make(vars_)
        result = lm.run(None, variables=vars_)
        self.assertEqual(result, ["restart: always"])

    def test_too_many_terms_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(["a", "b"], variables=vars_)

    def test_lowercase_docker_restart_policy_is_not_resolved_by_lookup(self):
        """Sanity check: the lookup does NOT silently fall back to
        `docker_restart_policy` from ansible-vars. That variable is
        only set as a Jinja-scope binding in a handful of templates,
        which the lookup cannot observe. Callers must pass the value
        explicitly when the Jinja-scope override matters."""
        vars_ = {
            "DEPLOYMENT_MODE": "compose",
            "docker_restart_policy": "no",
            "DOCKER_RESTART_POLICY": "always",
        }
        lm = self._make(vars_)
        result = lm.run([], variables=vars_)
        self.assertEqual(result, ["restart: always"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
