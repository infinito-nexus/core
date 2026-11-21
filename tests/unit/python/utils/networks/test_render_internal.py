from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_str
from utils.networks.render import render_compose_networks, render_container_networks

from ._render_helpers import _const_lookup_config, _const_lookup_database, _entity_name

APP = "web-app-semaphore"
SUBNET = "192.168.216.0/24"


def compose(mode, **kwargs):
    """Args:
    mode: compose or swarm.
    kwargs: the internal network arguments of ``compose_networks``.

    Returns:
        The rendered top-level block.
    """
    return render_compose_networks(
        application_id=APP,
        deployment_mode=mode,
        registry={},
        entity_name=_entity_name,
        lookup_config=_const_lookup_config(**{"networks.local.subnet": SUBNET}),
        lookup_database=_const_lookup_database(),
        **kwargs,
    )


def attachment(**kwargs):
    """Args:
    kwargs: the internal network arguments of ``container_networks``.

    Returns:
        The networks a service joins.
    """
    rendered = render_container_networks(
        application_id=APP,
        deployment_mode="compose",
        registry={},
        entity_name=_entity_name,
        lookup_config=_const_lookup_config(**{"networks.local.subnet": SUBNET}),
        lookup_database=_const_lookup_database(),
        **kwargs,
    )
    return load_yaml_str(rendered)["networks"]


class TestInternalNetworks(unittest.TestCase):
    def test_compose_defines_the_internal_network_after_the_role_networks(self):
        plain = compose("compose")
        extended = compose("compose", internal=("export",))
        self.assertTrue(extended.startswith(plain))
        networks = load_yaml_str(extended)["networks"]
        self.assertEqual(networks["export"], {"driver": "bridge", "internal": True})
        self.assertEqual(networks["default"]["name"], "semaphore")

    def test_swarm_defines_an_encrypted_internal_overlay(self):
        networks = load_yaml_str(compose("swarm", internal=("export",)))["networks"]
        self.assertEqual(
            networks["export"],
            {
                "driver": "overlay",
                "driver_opts": {"encrypted": "true"},
                "internal": True,
            },
        )
        unencrypted = load_yaml_str(
            compose("swarm", internal=("export",), swarm_encrypted=False)
        )["networks"]
        self.assertEqual(unencrypted["export"]["driver_opts"], {"encrypted": "false"})

    def test_a_project_of_its_own_defines_only_its_internal_network(self):
        networks = load_yaml_str(
            compose(
                "swarm", internal=("workspace",), internal_only=True, node_local=True
            )
        )["networks"]
        self.assertEqual(
            networks, {"workspace": {"driver": "bridge", "internal": True}}
        )
        self.assertEqual(compose("compose", internal_only=True), "")

    def test_a_member_joins_only_the_internal_network(self):
        self.assertEqual(attachment(internal="export"), {"export": {}})

    def test_the_egress_member_also_joins_default_without_an_alias(self):
        self.assertEqual(
            attachment(internal="export", egress=True), {"export": {}, "default": {}}
        )

    def test_negative_control_a_service_without_internal_joins_default(self):
        self.assertIn("default", attachment())
        self.assertNotIn("export", attachment(egress=True))

    def test_an_invalid_internal_name_is_refused(self):
        for name in ("", "default", "a b", "x:y"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    attachment(internal=name)
                with self.assertRaises(ValueError):
                    compose("compose", internal=(name,))


if __name__ == "__main__":
    unittest.main()
