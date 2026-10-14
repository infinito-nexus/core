"""Contract of the network registry and the per-role reachability resolution."""

from __future__ import annotations

import unittest

from utils.domains.default_primary import default_domain_primary
from utils.networks.reachability import (
    CLEARNET,
    MULTI,
    TOR,
    allowed_networks,
    effective_networks,
    is_network,
    network,
    network_of,
    resolve_node_mode,
    role_reachability,
    sibling_domain,
)

ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
DOMAIN = default_domain_primary()


def _cfg(**reachability) -> dict:
    return {"networks": {"reachability": reachability}} if reachability else {}


class TestNetworkOf(unittest.TestCase):
    def test_onion_suffix_is_tor(self) -> None:
        self.assertEqual(network_of(f"wazuh.{ONION}"), TOR)

    def test_trailing_dot_and_case_are_ignored(self) -> None:
        self.assertEqual(network_of(f"Wazuh.{ONION.upper()}."), TOR)

    def test_everything_else_is_clearnet(self) -> None:
        self.assertEqual(network_of(f"wazuh.{DOMAIN}"), CLEARNET)

    def test_is_network(self) -> None:
        self.assertTrue(is_network(ONION, TOR))
        self.assertFalse(is_network(DOMAIN, TOR))

    def test_reserved_network_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            network("handshake")

    def test_unknown_network_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            network("i2p")


class TestSiblingDomain(unittest.TestCase):
    def test_clearnet_subdomain_to_tor(self) -> None:
        self.assertEqual(
            sibling_domain(f"wazuh.{DOMAIN}", TOR, DOMAIN, ONION),
            f"wazuh.{ONION}",
        )

    def test_apex_to_tor_is_the_node_onion(self) -> None:
        self.assertEqual(sibling_domain(DOMAIN, TOR, DOMAIN, ONION), ONION)

    def test_tor_subdomain_to_clearnet(self) -> None:
        self.assertEqual(
            sibling_domain(f"wazuh.{ONION}", CLEARNET, DOMAIN, ONION),
            f"wazuh.{DOMAIN}",
        )

    def test_same_network_returns_itself(self) -> None:
        self.assertEqual(
            sibling_domain(f"wazuh.{DOMAIN}", CLEARNET, DOMAIN, ONION),
            f"wazuh.{DOMAIN}",
        )

    def test_foreign_domain_has_no_sibling(self) -> None:
        self.assertIsNone(sibling_domain("example.org", TOR, DOMAIN, ONION))

    def test_no_node_address_has_no_sibling(self) -> None:
        self.assertIsNone(sibling_domain(f"wazuh.{DOMAIN}", TOR, DOMAIN, ""))


class TestResolveNodeMode(unittest.TestCase):
    def test_empty_derives_multi_with_tor(self) -> None:
        self.assertEqual(resolve_node_mode("", tor_provided=True), MULTI)

    def test_empty_derives_clearnet_without_tor(self) -> None:
        self.assertEqual(resolve_node_mode(None, tor_provided=False), CLEARNET)

    def test_explicit_tor(self) -> None:
        self.assertEqual(resolve_node_mode("tor", tor_provided=True), TOR)

    def test_tor_mode_without_provider_fails(self) -> None:
        with self.assertRaises(ValueError):
            resolve_node_mode("multi", tor_provided=False)

    def test_unknown_mode_fails(self) -> None:
        with self.assertRaises(ValueError):
            resolve_node_mode("dual", tor_provided=True)


class TestRoleReachability(unittest.TestCase):
    def test_missing_means_every_network(self) -> None:
        self.assertEqual(role_reachability({}), ((), False))

    def test_empty_list_means_every_network(self) -> None:
        self.assertEqual(role_reachability(_cfg(modes=[])), ((), False))

    def test_multi_is_not_a_list_value(self) -> None:
        with self.assertRaises(ValueError):
            role_reachability(_cfg(modes=[CLEARNET, MULTI]))

    def test_single_mode_must_be_boolean(self) -> None:
        with self.assertRaises(TypeError):
            role_reachability(_cfg(single_mode="yes"))

    def test_tor_disabled_role_loses_tor(self) -> None:
        self.assertEqual(allowed_networks({}, tor_enabled=False), ((CLEARNET,), False))


class TestEffectiveNetworks(unittest.TestCase):
    """Every combination of node mode, ``modes`` and ``single_mode``."""

    CASES = (
        (CLEARNET, (), False, (CLEARNET,)),
        (TOR, (), False, (TOR,)),
        (MULTI, (), False, (CLEARNET, TOR)),
        (CLEARNET, (), True, (CLEARNET,)),
        (TOR, (), True, (TOR,)),
        (MULTI, (), True, (TOR,)),
        (CLEARNET, (CLEARNET,), False, (CLEARNET,)),
        (MULTI, (CLEARNET,), False, (CLEARNET,)),
        (MULTI, (CLEARNET,), True, (CLEARNET,)),
        (TOR, (TOR,), False, (TOR,)),
        (MULTI, (TOR,), False, (TOR,)),
        (MULTI, (CLEARNET, TOR), False, (CLEARNET, TOR)),
        (MULTI, (CLEARNET, TOR), True, (TOR,)),
    )

    FAILURES = (
        (TOR, (CLEARNET,), False),
        (TOR, (CLEARNET,), True),
        (CLEARNET, (TOR,), False),
        (CLEARNET, (TOR,), True),
    )

    def test_served_networks(self) -> None:
        for node_mode, modes, single, expected in self.CASES:
            allowed, parsed_single = allowed_networks(
                _cfg(modes=list(modes), single_mode=single), tor_enabled=True
            )
            with self.subTest(node=node_mode, modes=modes, single=single):
                self.assertEqual(
                    effective_networks(node_mode, allowed, parsed_single), expected
                )

    def test_mismatch_fails_loudly(self) -> None:
        for node_mode, modes, single in self.FAILURES:
            allowed, parsed_single = allowed_networks(
                _cfg(modes=list(modes), single_mode=single), tor_enabled=True
            )
            with (
                self.subTest(node=node_mode, modes=modes, single=single),
                self.assertRaisesRegex(ValueError, "web-app-x"),
            ):
                effective_networks(node_mode, allowed, parsed_single, app="web-app-x")


if __name__ == "__main__":
    unittest.main()
