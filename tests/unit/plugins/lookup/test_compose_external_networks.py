"""Unit tests for plugins/lookup/compose_external_networks.py.

Mocks the Ansible-side machinery and asserts the plugin glue resolves
variables and chains ``compute_external_network_roles`` correctly. The
computation itself is covered by tests.unit.utils.networks.test_render.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.compose_external_networks import LookupModule


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _make_lookup(vars_=None):
    lm = LookupModule()
    lm._templar = _Templar(vars_ or {})
    lm._loader = mock.MagicMock()
    return lm


class TestComposeExternalNetworksLookup(unittest.TestCase):
    def test_raises_when_positional_terms_supplied(self):
        lm = _make_lookup({"application_id": "x", "DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run(["unexpected"], variables=lm._templar.available_variables)

    def test_raises_when_application_id_missing(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_returns_role_list_from_helper(self):
        vars_ = {"application_id": "web-app-gitea", "DEPLOYMENT_MODE": "swarm"}
        lm = _make_lookup(vars_)

        with (
            mock.patch(
                "plugins.lookup.compose_external_networks.build_service_registry_from_applications",
                return_value={},
            ),
            mock.patch(
                "plugins.lookup.compose_external_networks.lookup_loader"
            ) as loader_mock,
            mock.patch(
                "plugins.lookup.compose_external_networks.compute_external_network_roles",
                return_value=["svc-db-redis", "svc-db-openldap"],
            ) as helper_mock,
        ):
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [""])
            result = lm.run([], variables=vars_)

        self.assertEqual(result, [["svc-db-redis", "svc-db-openldap"]])
        kwargs = helper_mock.call_args.kwargs
        self.assertEqual(kwargs["application_id"], "web-app-gitea")
        self.assertEqual(kwargs["deployment_mode"], "swarm")


if __name__ == "__main__":
    unittest.main()
