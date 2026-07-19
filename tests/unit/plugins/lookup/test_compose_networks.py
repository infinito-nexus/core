"""Unit tests for plugins/lookup/compose_networks.py.

Mocks the Ansible-side machinery (loader, lookup_loader, templar,
build_service_registry_from_applications) and
asserts that the plugin glue resolves variables and chains the underlying
``render_compose_networks`` function correctly.

The rendering correctness itself is covered by
tests.unit.utils.networks.test_render and the integration snapshot test.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.compose_networks import LookupModule


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


class TestComposeNetworksLookup(unittest.TestCase):
    def test_raises_when_positional_terms_supplied(self):
        lm = _make_lookup({"application_id": "x", "DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run(["unexpected"], variables=lm._templar.available_variables)

    def test_raises_when_application_id_missing(self):
        lm = _make_lookup({"DEPLOYMENT_MODE": "swarm"})
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})

    def test_chains_render_with_resolved_vars(self):
        vars_ = {
            "application_id": "web-app-baserow",
            "DEPLOYMENT_MODE": "swarm",
            "swarm": {"network": {"encryption": False}},
        }
        lm = _make_lookup(vars_)

        with (
            mock.patch(
                "plugins.lookup.compose_networks.build_service_registry_from_applications",
                return_value={},
            ),
            mock.patch("plugins.lookup.compose_networks.lookup_loader") as loader_mock,
            mock.patch(
                "plugins.lookup.compose_networks.render_compose_networks",
                return_value="RENDERED",
            ) as render_mock,
        ):
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [""])

            result = lm.run([], variables=vars_)

        self.assertEqual(result, ["RENDERED"])
        kwargs = render_mock.call_args.kwargs
        self.assertEqual(kwargs["application_id"], "web-app-baserow")
        self.assertEqual(kwargs["deployment_mode"], "swarm")
        # swarm.network.encryption: False is honoured
        self.assertFalse(kwargs["swarm_encrypted"])

    def test_swarm_encrypted_defaults_to_true_when_unset(self):
        vars_ = {
            "application_id": "web-app-x",
            "DEPLOYMENT_MODE": "swarm",
        }
        lm = _make_lookup(vars_)

        with (
            mock.patch(
                "plugins.lookup.compose_networks.build_service_registry_from_applications",
                return_value={},
            ),
            mock.patch("plugins.lookup.compose_networks.lookup_loader") as loader_mock,
            mock.patch(
                "plugins.lookup.compose_networks.render_compose_networks",
                return_value="RENDERED",
            ) as render_mock,
        ):
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [""])
            lm.run([], variables=vars_)

        self.assertTrue(render_mock.call_args.kwargs["swarm_encrypted"])

    def test_lookup_closures_pass_arguments_in_expected_order(self):
        # Pin the call shape of the closures that the plugin synthesises:
        #   config_lookup.run([app, path, default], variables=vars_)
        #   database_lookup.run([app, key], variables=vars_)
        # A regression that swaps app/path or drops the variables kwarg would
        # break at runtime but stay green with naive MagicMock stubs.
        vars_ = {
            "application_id": "web-app-x",
            "DEPLOYMENT_MODE": "swarm",
        }
        lm = _make_lookup(vars_)

        config_calls: list[tuple] = []
        database_calls: list[tuple] = []

        def _config_run(args, **kwargs):
            config_calls.append((tuple(args), kwargs))
            return [args[2] if len(args) > 2 else None]

        def _database_run(args, **kwargs):
            database_calls.append((tuple(args), kwargs))
            return [""]

        def _exercise(*_, lookup_config, lookup_database, **__):
            # Render-side calls the closures; pretend it does so with known args.
            lookup_config("web-app-x", "services.sso.enabled", False)
            lookup_database("web-app-x", "id")
            return "RENDERED"

        with (
            mock.patch(
                "plugins.lookup.compose_networks.build_service_registry_from_applications",
                return_value={},
            ),
            mock.patch("plugins.lookup.compose_networks.lookup_loader") as loader_mock,
            mock.patch(
                "plugins.lookup.compose_networks.render_compose_networks",
                side_effect=_exercise,
            ),
        ):

            def _get(name, **_):
                if name == "config":
                    return mock.MagicMock(run=_config_run)
                if name == "applications":
                    return mock.MagicMock(run=lambda *_a, **_k: [{}])
                return mock.MagicMock(run=_database_run)

            loader_mock.get.side_effect = _get
            lm.run([], variables=vars_)

        self.assertEqual(len(config_calls), 1)
        args, kwargs = config_calls[0]
        self.assertEqual(args, ("web-app-x", "services.sso.enabled", False))
        self.assertEqual(kwargs.get("variables"), vars_)

        self.assertEqual(len(database_calls), 1)
        args, kwargs = database_calls[0]
        self.assertEqual(args, ("web-app-x", "id"))
        self.assertEqual(kwargs.get("variables"), vars_)


if __name__ == "__main__":
    unittest.main()
