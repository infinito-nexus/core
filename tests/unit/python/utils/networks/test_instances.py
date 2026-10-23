"""Contract of the per-network instance naming."""

from __future__ import annotations

import unittest

from utils.domains.default_primary import default_domain_primary
from utils.networks.instances import labelled, labelled_file, network_instances
from utils.networks.reachability import CLEARNET, TOR, network

ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
DOMAIN = default_domain_primary()


class TestNetworkInstances(unittest.TestCase):
    def test_a_single_network_app_keeps_an_empty_label(self):
        self.assertEqual(
            network_instances(f"app.{DOMAIN}"), [{"network": CLEARNET, "label": ""}]
        )

    def test_each_further_network_carries_its_registry_label(self):
        self.assertEqual(
            network_instances([f"app.{DOMAIN}", f"app.{ONION}", f"www.{DOMAIN}"]),
            [
                {"network": CLEARNET, "label": ""},
                {"network": TOR, "label": network(TOR).label},
            ],
        )

    def test_an_onion_only_app_keeps_an_empty_label_on_tor(self):
        self.assertEqual(
            network_instances({"app": f"app.{ONION}"}), [{"network": TOR, "label": ""}]
        )


class TestLabelled(unittest.TestCase):
    def test_an_empty_label_keeps_the_name(self):
        self.assertEqual(labelled("dashboard", "", "-"), "dashboard")
        self.assertEqual(labelled_file("config.yaml", ""), "config.yaml")

    def test_a_label_suffixes_the_name_and_the_file_stem(self):
        self.assertEqual(labelled("http", "onion", "_"), "http_onion")
        self.assertEqual(labelled_file("config.yaml", "onion"), "config-onion.yaml")
        self.assertEqual(labelled_file("proxy", "onion"), "proxy-onion")


if __name__ == "__main__":
    unittest.main()
