"""Unit tests for plugins/lookup/shared_network_key.py.

Mocks the Ansible-side machinery and asserts that the plugin glue resolves the
term and chains ``shared_network_compose_key`` correctly. The key derivation
itself is covered by tests.unit.utils.networks.test_render.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.shared_network_key import LookupModule


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


def _patched(lm, vars_, return_value="default"):
    return (
        mock.patch(
            "utils.networks.lookup_context.build_service_registry_from_applications",
            return_value={},
        ),
        mock.patch("utils.networks.lookup_context.lookup_loader"),
        mock.patch(
            "plugins.lookup.shared_network_key.shared_network_compose_key",
            return_value=return_value,
        ),
    )


class TestSharedNetworkKeyLookup(unittest.TestCase):
    def test_raises_without_a_term(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_raises_with_more_than_one_term(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run(["a", "b"], variables={})

    def test_returns_the_derived_key(self):
        vars_ = {"DEPLOYMENT_MODE": "compose"}
        lm = _make_lookup(vars_)
        registry_patch, loader_patch, key_patch = _patched(lm, vars_, "seaweedfs")
        with registry_patch, loader_patch as loader_mock, key_patch as key_mock:
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
            result = lm.run(["web-app-seaweedfs"], variables=vars_)

        self.assertEqual(result, ["seaweedfs"])
        kwargs = key_mock.call_args.kwargs
        self.assertEqual(kwargs["application_id"], "web-app-seaweedfs")
        self.assertEqual(kwargs["deployment_mode"], "compose")
        self.assertFalse(kwargs["node_local"])

    def test_compose_mode_force_overrides_deployment_mode(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm", "compose_mode_force": "compose"}
        lm = _make_lookup(vars_)
        registry_patch, loader_patch, key_patch = _patched(lm, vars_)
        with registry_patch, loader_patch as loader_mock, key_patch as key_mock:
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
            lm.run(["web-app-x"], variables=vars_)

        self.assertEqual(key_mock.call_args.kwargs["deployment_mode"], "compose")

    def test_node_local_is_forwarded(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = _make_lookup(vars_)
        registry_patch, loader_patch, key_patch = _patched(lm, vars_)
        with registry_patch, loader_patch as loader_mock, key_patch as key_mock:
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
            lm.run(["web-app-x"], variables=vars_, node_local=True)

        self.assertTrue(key_mock.call_args.kwargs["node_local"])

    def test_lookup_closures_pass_arguments_in_expected_order(self):
        vars_ = {"DEPLOYMENT_MODE": "swarm"}
        lm = _make_lookup(vars_)
        seen: list[tuple] = []

        def _runner(terms, variables=None):
            seen.append((tuple(terms), variables is vars_))
            return [{}]

        registry_patch, loader_patch, key_patch = _patched(lm, vars_)
        with registry_patch, loader_patch as loader_mock, key_patch as key_mock:
            loader_mock.get.return_value = mock.MagicMock(run=_runner)
            lm.run(["web-app-x"], variables=vars_)
            kwargs = key_mock.call_args.kwargs
            kwargs["lookup_config"]("app", "networks.local.subnet", "fallback")
            kwargs["lookup_database"]("app", "name")

        self.assertIn((("app", "networks.local.subnet", "fallback"), True), seen)
        self.assertIn((("app", "name"), True), seen)


if __name__ == "__main__":
    unittest.main()
