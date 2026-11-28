"""Unit tests for plugins/lookup/stream_relay_ports.py and stream_relay_networks.py.

Mocks the Ansible-side machinery and asserts the plugin glue: the rendering
role and the effective mode reach the helper, its result comes back as the
lookup's value, and a declaration error becomes an AnsibleError. The
computation itself is covered by tests/unit/python/utils/networks/test_stream_relay.py.
"""

from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup import stream_relay_networks, stream_relay_ports

TERM = {
    "service": "openldap",
    "protocol": "ldaps",
    "application_id": "svc-db-openldap",
    "container": "same",
    "mode": "host",
}
RELAY = {"name": "openldap-relay", "subnet": "192.168.105.48/28", "stack": "openldap"}
PROXY_VARS = {"application_id": "svc-prx-openresty", "DEPLOYMENT_MODE": "swarm"}


class _Templar:
    def __init__(self, vars_=None):
        self.available_variables = vars_ or {}

    def template(self, value, **_):
        return value


def _run(module, vars_, helper):
    lookup = module.LookupModule()
    lookup._templar = _Templar(vars_)
    lookup._loader = mock.MagicMock()
    name = module.__name__.rsplit(".", 1)[-1]
    with (
        mock.patch(
            "utils.networks.lookup_context.build_service_registry_from_applications",
            return_value={},
        ),
        mock.patch("utils.networks.lookup_context.lookup_loader") as loader_mock,
        mock.patch.object(module, name, **helper) as helper_mock,
    ):
        loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
        return lookup.run([], variables=vars_), helper_mock


class TestBothLookups(unittest.TestCase):
    MODULES = (stream_relay_ports, stream_relay_networks)

    def test_positional_terms_are_refused(self):
        for module in self.MODULES:
            with self.subTest(module=module.__name__):
                lookup = module.LookupModule()
                lookup._templar = _Templar(dict(PROXY_VARS))
                lookup._loader = mock.MagicMock()
                with self.assertRaises(AnsibleError):
                    lookup.run(["svc-db-openldap"], variables={})

    def test_a_missing_application_id_is_refused(self):
        for module in self.MODULES:
            with (
                self.subTest(module=module.__name__),
                self.assertRaises(AnsibleError),
            ):
                _run(module, {"DEPLOYMENT_MODE": "swarm"}, {"return_value": []})

    def test_a_declaration_error_becomes_an_ansible_error(self):
        for module in self.MODULES:
            with (
                self.subTest(module=module.__name__),
                self.assertRaisesRegex(AnsibleError, "stream_relay needs ports"),
            ):
                _run(
                    module,
                    dict(PROXY_VARS),
                    {"side_effect": ValueError("overlay.stream_relay needs ports")},
                )


class TestStreamRelayPortsLookup(unittest.TestCase):
    def test_the_terms_come_back_as_the_lookup_list(self):
        result, _ = _run(stream_relay_ports, dict(PROXY_VARS), {"return_value": [TERM]})
        self.assertEqual(result, [TERM])

    def test_the_rendering_role_and_the_forced_mode_reach_the_helper(self):
        _, helper = _run(
            stream_relay_ports,
            {**PROXY_VARS, "compose_mode_force": "compose"},
            {"return_value": []},
        )
        kwargs = helper.call_args.kwargs
        self.assertEqual(kwargs["application_id"], "svc-prx-openresty")
        self.assertEqual(kwargs["deployment_mode"], "compose")


class TestStreamRelayNetworksLookup(unittest.TestCase):
    def test_the_networks_come_back_as_one_list(self):
        result, _ = _run(
            stream_relay_networks, dict(PROXY_VARS), {"return_value": [RELAY]}
        )
        self.assertEqual(result, [[RELAY]])

    def test_the_pre_create_ignores_the_forced_mode_like_the_role_overlays(self):
        _, helper = _run(
            stream_relay_networks,
            {**PROXY_VARS, "compose_mode_force": "compose"},
            {"return_value": []},
        )
        kwargs = helper.call_args.kwargs
        self.assertEqual(kwargs["application_id"], "svc-prx-openresty")
        self.assertEqual(kwargs["deployment_mode"], "swarm")


if __name__ == "__main__":
    unittest.main()
