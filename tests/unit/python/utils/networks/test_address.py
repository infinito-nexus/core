"""Contract of the subnet address helpers.

The regex is consumed by JGroups' `match-address`, which applies it to the
addresses of local interfaces with implicit anchoring, so the tests match with
`fullmatch` over valid dotted quads only.
"""

from __future__ import annotations

import ipaddress
import re
import unittest

from utils.networks.address import subnet_address_regex, subnet_gateway

UNIVERSE = ipaddress.ip_network("192.168.0.0/16")


class TestSubnetAddressRegexShape(unittest.TestCase):
    def test_slash_24_pins_three_octets(self) -> None:
        self.assertEqual(subnet_address_regex("192.168.24.0/24"), r"192\.168\.24\.\d+")

    def test_slash_16_pins_two_octets(self) -> None:
        self.assertEqual(subnet_address_regex("192.168.0.0/16"), r"192\.168\.\d+\.\d+")

    def test_slash_8_pins_one_octet(self) -> None:
        self.assertEqual(subnet_address_regex("10.0.0.0/8"), r"10\.\d+\.\d+\.\d+")

    def test_slash_23_enumerates_the_two_third_octets(self) -> None:
        self.assertEqual(
            subnet_address_regex("192.168.24.0/23"), r"192\.168\.(24|25)\.\d+"
        )

    def test_slash_30_enumerates_the_four_host_octets(self) -> None:
        self.assertEqual(
            subnet_address_regex("192.168.24.0/30"), r"192\.168\.24\.(0|1|2|3)"
        )

    def test_slash_32_is_a_single_literal_address(self) -> None:
        self.assertEqual(subnet_address_regex("192.168.24.13/32"), r"192\.168\.24\.13")

    def test_the_dots_are_escaped(self) -> None:
        pattern = re.compile(subnet_address_regex("192.168.24.0/24"))
        self.assertIsNone(pattern.fullmatch("192a168a24a13"))


class TestSubnetAddressRegexExactness(unittest.TestCase):
    """Exhaustive: over every address of a /16, matching must equal membership."""

    SUBNETS = (
        "192.168.24.0/24",
        "192.168.24.0/23",
        "192.168.16.0/20",
        "192.168.0.0/17",
        "192.168.24.128/25",
        "192.168.24.0/30",
        "192.168.24.13/32",
        "192.168.0.0/16",
    )

    def test_regex_membership_equals_network_membership(self) -> None:
        addresses = [(str(a), int(a)) for a in UNIVERSE]
        for subnet in self.SUBNETS:
            with self.subTest(subnet=subnet):
                network = ipaddress.ip_network(subnet)
                low, high = int(network.network_address), int(network.broadcast_address)
                pattern = re.compile(subnet_address_regex(subnet))
                mismatches = [
                    text
                    for text, value in addresses
                    if bool(pattern.fullmatch(text)) != (low <= value <= high)
                ]
                self.assertEqual(mismatches[:5], [], f"{len(mismatches)} mismatches")

    def test_it_rejects_addresses_outside_the_universe(self) -> None:
        pattern = re.compile(subnet_address_regex("192.168.24.0/24"))
        for outside in ("172.18.0.18", "192.168.200.15", "10.0.0.1", "192.169.24.13"):
            with self.subTest(address=outside):
                self.assertIsNone(pattern.fullmatch(outside))


class TestSubnetAddressRegexEveryPrefix(unittest.TestCase):
    def test_boundaries_hold_for_every_prefix_length(self) -> None:
        for prefix in range(8, 33):
            network = ipaddress.ip_network(f"10.20.30.40/{prefix}", strict=False)
            with self.subTest(prefix=prefix, network=str(network)):
                pattern = re.compile(subnet_address_regex(str(network)))
                self.assertIsNotNone(pattern.fullmatch(str(network.network_address)))
                self.assertIsNotNone(pattern.fullmatch(str(network.broadcast_address)))
                below = int(network.network_address) - 1
                above = int(network.broadcast_address) + 1
                if below >= 0:
                    self.assertIsNone(
                        pattern.fullmatch(str(ipaddress.ip_address(below)))
                    )
                if above < 2**32:
                    self.assertIsNone(
                        pattern.fullmatch(str(ipaddress.ip_address(above)))
                    )


class TestSubnetAddressRegexRejects(unittest.TestCase):
    def test_host_bits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            subnet_address_regex("192.168.24.13/24")

    def test_malformed_notation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            subnet_address_regex("not-a-subnet")

    def test_an_empty_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            subnet_address_regex("")


class TestSubnetGateway(unittest.TestCase):
    def test_slash_24(self) -> None:
        self.assertEqual(subnet_gateway("192.168.24.0/24"), "192.168.24.1")

    def test_slash_16(self) -> None:
        self.assertEqual(subnet_gateway("192.168.0.0/16"), "192.168.0.1")

    def test_slash_8(self) -> None:
        self.assertEqual(subnet_gateway("10.0.0.0/8"), "10.0.0.1")

    def test_an_unaligned_subnet_gets_its_own_gateway(self) -> None:
        self.assertEqual(subnet_gateway("192.168.24.128/25"), "192.168.24.129")

    def test_it_is_the_first_usable_address_for_every_prefix(self) -> None:
        for prefix in range(8, 32):
            network = ipaddress.ip_network(f"10.20.30.40/{prefix}", strict=False)
            with self.subTest(prefix=prefix):
                self.assertEqual(subnet_gateway(str(network)), str(network[1]))

    def test_host_bits_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            subnet_gateway("192.168.24.13/24")

    def test_malformed_notation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            subnet_gateway("not-a-subnet")

    def test_a_single_address_network_holds_no_gateway(self) -> None:
        with self.assertRaises(ValueError) as caught:
            subnet_gateway("10.0.0.1/32")
        self.assertIn("/32", str(caught.exception))


class TestBothAgreeOnEveryRoleSubnet(unittest.TestCase):
    def test_the_gateway_is_matched_by_the_regex(self) -> None:
        for subnet in TestSubnetAddressRegexExactness.SUBNETS:
            if ipaddress.ip_network(subnet).num_addresses < 2:
                continue
            with self.subTest(subnet=subnet):
                pattern = re.compile(subnet_address_regex(subnet))
                self.assertIsNotNone(pattern.fullmatch(subnet_gateway(subnet)))


if __name__ == "__main__":
    unittest.main()
