"""Unit tests for the container_deploy lookup plugin.

Pins the swarm ``deploy:`` head contract:

* non-swarm mode emits empty string, so callers need no mode guard.
* ``compose_mode_force`` overrides ``DEPLOYMENT_MODE``.
* the replica count is delegated to the compose_replicas SPOT: an explicit
  ``replicas=`` wins, an empty one falls back to the topology default.
* a role whose primary entity declares a placement gains the constraint
  block; one that declares none gains nothing.
* children are indented two spaces under ``deploy:`` so the caller's
  ``| indent(N)`` lands the whole block at N.
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

SWARM = {
    "DEPLOYMENT_MODE": "swarm",
    "application_id": "web-app-x",
    "groups": {"web-app-x": ["mgr-01", "wrk-01", "wrk-02"]},
}


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_container_deploy",
        str(PROJECT_ROOT / "plugins/lookup/container_deploy.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables=None):
        self.available_variables = available_variables or {}

    def template(self, value):
        return value


class TestContainerDeployLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_lookup()

    def setUp(self):
        self._real_placement = self.mod.get_role_placement
        self.placement = None
        self.mod.get_role_placement = lambda _role: self.placement

    def tearDown(self):
        self.mod.get_role_placement = self._real_placement

    def _run(self, variables, **kwargs):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm.run([], variables=variables, **kwargs)[0]

    def test_compose_mode_emits_nothing(self):
        self.assertEqual(self._run({**SWARM, "DEPLOYMENT_MODE": "compose"}), "")

    def test_missing_deployment_mode_emits_nothing(self):
        self.assertEqual(self._run({"application_id": "web-app-x"}), "")

    def test_compose_mode_force_overrides_deployment_mode(self):
        vars_ = {**SWARM, "DEPLOYMENT_MODE": "compose", "compose_mode_force": "swarm"}
        self.assertEqual(self._run(vars_), "deploy:\n  replicas: 3")

    def test_topology_default_without_an_override(self):
        self.assertEqual(self._run(SWARM), "deploy:\n  replicas: 3")

    def test_empty_override_falls_back_to_the_topology_default(self):
        self.assertEqual(self._run(SWARM, replicas=""), "deploy:\n  replicas: 3")

    def test_explicit_override_wins(self):
        self.assertEqual(self._run(SWARM, replicas=1), "deploy:\n  replicas: 1")

    def test_placement_is_appended_when_the_role_declares_one(self):
        self.placement = "manager"
        self.assertEqual(
            self._run(SWARM, replicas=1),
            "deploy:\n"
            "  replicas: 1\n"
            "  placement:\n"
            "    constraints:\n"
            "      - node.role == manager",
        )

    def test_a_positional_term_is_rejected(self):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(SWARM)
        lm._loader = None
        with self.assertRaises(AnsibleError):
            lm.run([1], variables=SWARM)

    def test_missing_application_id_is_rejected(self):
        with self.assertRaises(AnsibleError):
            self._run({"DEPLOYMENT_MODE": "swarm"})


if __name__ == "__main__":
    unittest.main()
