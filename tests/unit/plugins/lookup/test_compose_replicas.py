"""Unit tests for the compose_replicas lookup plugin.

Pins the SPOT contract for swarm replica calculation:

* swarm mode: emits `replicas: N` where N defaults to
  `len(groups[application_id])` or the override term.
* non-swarm mode: emits empty string.
* missing group / empty topology default: clamped to 1.
* an explicit override term is respected as-is, including 0 (lets a
  service stay unscheduled until the role scales it up).
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_compose_replicas",
        str(PROJECT_ROOT / "plugins/lookup/compose_replicas.py"),
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


class TestComposeReplicasLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _make(self, variables):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm

    def test_compose_mode_no_arg_emits_empty(self):
        vars_ = {
            "DEPLOYMENT_MODE": "compose",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["h1", "h2", "h3"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), [""])

    def test_compose_mode_with_arg_emits_empty(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = self._make(vars_)
        self.assertEqual(lm.run([3], variables=vars_), [""])

    def test_missing_deployment_mode_defaults_to_compose(self):
        vars_ = {
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["h1", "h2"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), [""])

    def test_swarm_mode_default_uses_group_length(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["mgr-01", "wrk-01", "wrk-02"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), ["replicas: 3"])

    def test_swarm_mode_single_host_yields_one(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["h1"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), ["replicas: 1"])

    def test_swarm_mode_empty_group_falls_back_to_one(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {"web-app-x": []},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), ["replicas: 1"])

    def test_swarm_mode_missing_group_falls_back_to_one(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), ["replicas: 1"])

    def test_swarm_mode_explicit_override(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["h1", "h2", "h3"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([5], variables=vars_), ["replicas: 5"])

    def test_swarm_mode_override_string_coerced(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        self.assertEqual(lm.run(["2"], variables=vars_), ["replicas: 2"])

    def test_swarm_mode_override_zero_respected(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        self.assertEqual(lm.run([0], variables=vars_), ["replicas: 0"])

    def test_too_many_terms_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run([1, 2], variables=vars_)

    def test_invalid_override_raises(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = self._make(vars_)
        with self.assertRaises(AnsibleError):
            lm.run(["not-a-number"], variables=vars_)

    def test_swarm_mode_whitespace_in_mode_normalised(self):
        vars_ = {
            "DEPLOYMENT_MODE": "  swarm  ",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["h1", "h2"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run([], variables=vars_), ["replicas: 2"])

    def test_none_terms_treated_as_no_args(self):
        vars_ = {
            "DEPLOYMENT_MODE": "swarm",
            "application_id": "web-app-x",
            "groups": {"web-app-x": ["a", "b"]},
        }
        lm = self._make(vars_)
        self.assertEqual(lm.run(None, variables=vars_), ["replicas: 2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
