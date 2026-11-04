"""Contract of the per-network instance naming."""

from __future__ import annotations

import unittest

from utils.domains.default_primary import default_domain_primary
from utils.networks.instances import (
    labelled,
    labelled_file,
    network_instances,
    vhost_label,
)
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


class TestVhostLabel(unittest.TestCase):
    def setUp(self):
        self.multi = [f"app.{DOMAIN}", f"app.{ONION}"]

    def test_the_first_network_vhost_keeps_an_empty_label(self):
        self.assertEqual(vhost_label(self.multi, f"app.{DOMAIN}"), "")

    def test_a_further_network_vhost_carries_its_registry_label(self):
        self.assertEqual(vhost_label(self.multi, f"app.{ONION}"), network(TOR).label)

    def test_the_vhost_is_matched_case_insensitively(self):
        self.assertEqual(
            vhost_label(self.multi, f"APP.{ONION.upper()}"), network(TOR).label
        )

    def test_a_single_network_vhost_keeps_an_empty_label(self):
        self.assertEqual(vhost_label({"app": f"app.{ONION}"}, f"app.{ONION}"), "")

    def test_a_foreign_vhost_takes_the_label_of_the_first_network(self):
        self.assertEqual(vhost_label(self.multi, f"other.{ONION}"), "")

    def test_an_application_without_domains_keeps_an_empty_label(self):
        self.assertEqual(vhost_label([], f"app.{DOMAIN}"), "")


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
