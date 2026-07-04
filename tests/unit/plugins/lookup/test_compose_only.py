"""Unit tests for the compose_only lookup plugin.

Pins the contract for the generic SPOT lookup that gates compose-only
YAML keys (container_name, pull_policy, ...) per DEPLOYMENT_MODE.
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_compose_only",
        str(PROJECT_ROOT / "plugins/lookup/compose_only.py"),
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


class TestComposeOnlyLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _make(self, variables):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def test_compose_mode_emits_container_name(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run(["container_name", "myapp"], variables=vars_)
        self.assertEqual(result, ['container_name: "myapp"'])

    def test_compose_mode_emits_pull_policy(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run(["pull_policy", "never"], variables=vars_)
        self.assertEqual(result, ['pull_policy: "never"'])

    def test_compose_mode_emits_arbitrary_key(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run(["some_other_key", "some_value"], variables=vars_)
        self.assertEqual(result, ['some_other_key: "some_value"'])

    def test_swarm_mode_emits_empty(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        for key, value in [
            ("container_name", "myapp"),
            ("pull_policy", "never"),
            ("anything", "anyvalue"),
        ]:
            with self.subTest(key=key):
                self.assertEqual(lm.run([key, value], variables=vars_), [""])

    def test_swarm_mode_with_surrounding_whitespace(self):
        vars_ = {"DEPLOYMENT_MODE": "  swarm  "}
        lm = self._make(vars_)
        result = lm.run(["pull_policy", "never"], variables=vars_)
        self.assertEqual(result, [""])

    def test_missing_deployment_mode_defaults_to_compose(self):
        vars_ = {}
        lm = self._make(vars_)
        result = lm.run(["container_name", "myapp"], variables=vars_)
        self.assertEqual(result, ['container_name: "myapp"'])

    def test_empty_terms_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run([], variables=vars_)

    def test_none_terms_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(None, variables=vars_)

    def test_single_term_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(["container_name"], variables=vars_)

    def test_too_many_terms_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(["a", "b", "c"], variables=vars_)

    def test_empty_key_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(["", "value"], variables=vars_)

    def test_non_string_value_coerced_to_string(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        result = lm.run(["container_name", 42], variables=vars_)
        self.assertEqual(result, ['container_name: "42"'])

    def test_compose_mode_force_overrides_swarm_cluster_mode(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm", "compose_mode_force": "compose"}
        lm = self._make(vars_)
        result = lm.run(["container_name", "mdad"], variables=vars_)
        self.assertEqual(result, ['container_name: "mdad"'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
