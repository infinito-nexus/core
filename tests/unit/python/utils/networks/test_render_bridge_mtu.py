from __future__ import annotations

import unittest

import yaml

from utils.networks.render import BRIDGE_MTU_OPTION, render_compose_networks

from ._render_helpers import _const_lookup_config, _const_lookup_database, _entity_name

OPENRESTY = {
    "openresty": {
        "role": "svc-prx-openresty",
        "entity_name": "openresty",
        "overlay": {"modes": ["swarm"], "topology": "default_net"},
    },
}
SUBNET = {"networks.local.subnet": "10.0.0.0/24"}


def default_network(application_id, deployment_mode, bridge_mtu, registry=None, config=None):
    rendered = render_compose_networks(
        application_id=application_id,
        deployment_mode=deployment_mode,
        registry=registry or {},
        entity_name=_entity_name,
        lookup_config=_const_lookup_config(**(config or {})),
        lookup_database=_const_lookup_database(),
        bridge_mtu=bridge_mtu,
    )
    return yaml.safe_load(rendered)["networks"]["default"] or {}


class TestBridgeMtu(unittest.TestCase):
    def test_every_compose_bridge_carries_the_daemon_mtu(self):
        cases = {
            "own shared_net provider": ("svc-prx-openresty", OPENRESTY, None),
            "pinned subnet": ("web-app-anything", None, SUBNET),
            "docker-assigned subnet": ("web-app-anything", None, None),
        }
        for label, (application_id, registry, config) in cases.items():
            with self.subTest(label):
                network = default_network(application_id, "compose", 1400, registry, config)
                self.assertEqual(network["driver_opts"], {BRIDGE_MTU_OPTION: "1400"})

    def test_a_node_local_swarm_bridge_carries_the_daemon_mtu(self):
        rendered = render_compose_networks(
            application_id="svc-runner",
            deployment_mode="swarm",
            registry={},
            entity_name=_entity_name,
            lookup_config=_const_lookup_config(**SUBNET),
            lookup_database=_const_lookup_database(),
            node_local=True,
            bridge_mtu=1400,
        )
        network = yaml.safe_load(rendered)["networks"]["default"]
        self.assertEqual(network["driver"], "bridge")
        self.assertEqual(network["driver_opts"], {BRIDGE_MTU_OPTION: "1400"})

    def test_a_swarm_overlay_keeps_its_own_options(self):
        network = default_network("web-app-anything", "swarm", 1400, None, SUBNET)
        self.assertEqual(network["driver"], "overlay")
        self.assertNotIn(BRIDGE_MTU_OPTION, network["driver_opts"])

    def test_without_a_daemon_mtu_the_bridge_renders_as_before(self):
        for application_id, registry, config in (
            ("svc-prx-openresty", OPENRESTY, None),
            ("web-app-anything", None, SUBNET),
        ):
            with self.subTest(application_id):
                network = default_network(application_id, "compose", None, registry, config)
                self.assertNotIn("driver_opts", network)


if __name__ == "__main__":
    unittest.main()
