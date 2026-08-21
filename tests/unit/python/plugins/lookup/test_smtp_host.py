"""Unit tests for the smtp_host lookup plugin.

Pins the SMTP endpoint matrix msmtp relays through: the configured relay in
production, loopback on a host that carries the stack, and the swarm manager's
routing mesh on a bare infra node inside the containerised test rig.
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

RELAY = "mail.infinito.example"
MANAGER = "swarm-manager-01"


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_smtp_host",
        str(PROJECT_ROOT / "plugins/lookup/smtp_host.py"),
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


def _email(external=True, host=RELAY):
    return {"external": external, "host": host}


class TestSmtpHostLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LookupModule = _load_lookup()

    def _resolve(self, variables, email=None):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar(variables)
        lm._loader = None
        return lm.run([email if email is not None else _email()], variables=variables)[
            0
        ]

    def test_production_keeps_the_configured_relay(self):
        vars_ = {"DOCKER_IN_CONTAINER": False, "DEPLOYMENT_MODE": "swarm"}
        self.assertEqual(self._resolve(vars_), RELAY)

    def test_non_external_mail_keeps_the_configured_relay(self):
        vars_ = {"DOCKER_IN_CONTAINER": True, "DEPLOYMENT_MODE": "swarm"}
        email = _email(external=False, host="localhost")
        self.assertEqual(self._resolve(vars_, email), "localhost")

    def test_compose_rig_uses_loopback(self):
        vars_ = {"DOCKER_IN_CONTAINER": True, "DEPLOYMENT_MODE": "compose"}
        self.assertEqual(self._resolve(vars_), "127.0.0.1")

    def test_swarm_node_uses_loopback(self):
        vars_ = {
            "DOCKER_IN_CONTAINER": True,
            "DEPLOYMENT_MODE": "swarm",
            "group_names": ["svc-swarm-node"],
        }
        self.assertEqual(self._resolve(vars_), "127.0.0.1")

    def test_infra_node_enters_through_the_manager(self):
        vars_ = {
            "DOCKER_IN_CONTAINER": True,
            "DEPLOYMENT_MODE": "swarm",
            "group_names": ["svc-nfs-server"],
            "groups": {"svc-swarm-manager": [MANAGER, "swarm-manager-02"]},
        }
        self.assertEqual(self._resolve(vars_), MANAGER)

    def test_infra_node_without_manager_falls_back_to_the_relay(self):
        vars_ = {
            "DOCKER_IN_CONTAINER": True,
            "DEPLOYMENT_MODE": "swarm",
            "group_names": ["svc-nfs-server"],
            "groups": {"svc-swarm-manager": []},
        }
        self.assertEqual(self._resolve(vars_), RELAY)

    def test_string_booleans_are_coerced(self):
        vars_ = {"DOCKER_IN_CONTAINER": "True", "DEPLOYMENT_MODE": "compose"}
        self.assertEqual(self._resolve(vars_, _email(external="yes")), "127.0.0.1")

    def test_swarm_node_wins_over_a_populated_manager_group(self):
        vars_ = {
            "DOCKER_IN_CONTAINER": True,
            "DEPLOYMENT_MODE": "swarm",
            "group_names": ["svc-swarm-node"],
            "groups": {"svc-swarm-manager": [MANAGER]},
        }
        self.assertEqual(self._resolve(vars_), "127.0.0.1")

    def test_missing_terms_raise(self):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar({})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_too_many_terms_raise(self):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar({})
        with self.assertRaises(AnsibleError):
            lm.run([_email(), _email()], variables={})

    def test_non_mapping_term_raises(self):
        lm = self.LookupModule()
        lm._templar = _DummyTemplar({})
        with self.assertRaises(AnsibleError):
            lm.run([RELAY], variables={})


if __name__ == "__main__":
    unittest.main(verbosity=2)
