"""Contract of ``lookup('network_siblings')``: every logical domain renders
once per network its app is served on, and exactly once overall."""

from __future__ import annotations

import unittest

from plugins.lookup.network_siblings import network_family, served_siblings
from utils.domains.default_primary import default_domain_primary

ONION = "abc123def456ghij789klmno000pqrstuvwx111yz222abc333def444gh.onion"
PRIMARY = default_domain_primary()


class TestServedSiblings(unittest.TestCase):
    def test_multi_app_renders_both_networks_from_the_canonical_domain(self) -> None:
        domains = {"web-app-bluesky": [f"x.{PRIMARY}", f"x.{ONION}"]}
        self.assertEqual(
            served_siblings(f"x.{PRIMARY}", domains, PRIMARY, ONION),
            [f"x.{PRIMARY}", f"x.{ONION}"],
        )

    def test_multi_app_skips_the_non_canonical_sibling(self) -> None:
        domains = {"web-app-bluesky": [f"x.{PRIMARY}", f"x.{ONION}"]}
        self.assertEqual(served_siblings(f"x.{ONION}", domains, PRIMARY, ONION), [])

    def test_tor_only_app_maps_a_raw_clearnet_domain_to_its_onion(self) -> None:
        domains = {"web-app-bluesky": [f"x.{ONION}"]}
        self.assertEqual(
            served_siblings(f"x.{PRIMARY}", domains, PRIMARY, ONION), [f"x.{ONION}"]
        )

    def test_clearnet_only_app_renders_one_vhost(self) -> None:
        domains = {"web-app-bluesky": [f"x.{PRIMARY}"]}
        self.assertEqual(
            served_siblings(f"x.{PRIMARY}", domains, PRIMARY, ONION),
            [f"x.{PRIMARY}"],
        )

    def test_named_canonicals_fan_out_per_key(self) -> None:
        domains = {
            "web-app-bluesky": {
                "api": f"api.{PRIMARY}",
                "web": f"web.{PRIMARY}",
                "api_onion": f"api.{ONION}",
                "web_onion": f"web.{ONION}",
            }
        }
        self.assertEqual(
            served_siblings(f"web.{PRIMARY}", domains, PRIMARY, ONION),
            [f"web.{PRIMARY}", f"web.{ONION}"],
        )

    def test_looping_over_every_served_domain_renders_each_sibling_once(self) -> None:
        served = [f"a.{PRIMARY}", f"b.{PRIMARY}", f"a.{ONION}", f"b.{ONION}"]
        domains = {"web-app-bluesky": served}
        rendered = [
            vhost
            for domain in served
            for vhost in served_siblings(domain, domains, PRIMARY, ONION)
        ]
        self.assertEqual(rendered, [served[0], served[2], served[1], served[3]])

    def test_named_canonicals_render_each_sibling_once_across_all_keys(self) -> None:
        domains = {
            "web-app-bluesky": {
                "api": f"api.{PRIMARY}",
                "web": f"web.{PRIMARY}",
                "api_onion": f"api.{ONION}",
                "web_onion": f"web.{ONION}",
            }
        }
        rendered = [
            vhost
            for domain in domains["web-app-bluesky"].values()
            for vhost in served_siblings(domain, domains, PRIMARY, ONION)
        ]
        self.assertCountEqual(rendered, list(domains["web-app-bluesky"].values()))

    def test_unknown_domain_renders_as_given(self) -> None:
        self.assertEqual(
            served_siblings("elsewhere.example", {}, PRIMARY, ONION),
            ["elsewhere.example"],
        )

    def test_node_without_tor_renders_as_given(self) -> None:
        domains = {"web-app-bluesky": [f"x.{PRIMARY}"]}
        self.assertEqual(
            served_siblings(f"x.{PRIMARY}", domains, PRIMARY, ""),
            [f"x.{PRIMARY}"],
        )


class TestNetworkFamily(unittest.TestCase):
    def test_every_sibling_names_the_same_family_canonical_first(self) -> None:
        domains = {"web-app-bluesky": [f"x.{PRIMARY}", f"x.{ONION}"]}
        for domain in domains["web-app-bluesky"]:
            with self.subTest(domain=domain):
                self.assertEqual(
                    network_family(domain, domains, PRIMARY, ONION),
                    [f"x.{PRIMARY}", f"x.{ONION}"],
                )

    def test_tor_only_app_maps_a_raw_clearnet_domain_to_its_onion(self) -> None:
        domains = {"web-app-bluesky": [f"x.{ONION}"]}
        self.assertEqual(
            network_family(f"x.{PRIMARY}", domains, PRIMARY, ONION), [f"x.{ONION}"]
        )

    def test_unknown_domain_is_its_own_family(self) -> None:
        self.assertEqual(
            network_family("elsewhere.example", {}, PRIMARY, ONION),
            ["elsewhere.example"],
        )


if __name__ == "__main__":
    unittest.main()
