"""Every worktree slot must pin a valid swarm lab subnet of its own.

`scripts/system/worktree/up.sh` derives `INFINITO_SWARM_LAB_SUBNET` from the
slot. A derivation that overflows an octet yields an address Docker rejects at
network creation, and one that lands in a reserved range breaks the swarm at
runtime: inside NETWORK_TOR_VIRTUAL_CIDR svc-net-tor redirects every TCP
connection to Tor's TransPort, so the nodes cannot reach each other.
"""

from __future__ import annotations

import ipaddress
import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.env.parser import parse_static_env

from . import PROJECT_ROOT

_UP_SH = PROJECT_ROOT / "scripts/system/worktree/up.sh"
_NETWORKS = PROJECT_ROOT / "group_vars/all/08_networks.yml"
_MAX_SLOT_RE = re.compile(r"^max_slot=(?P<value>\d+)$", re.MULTILINE)
_LAB_PREFIX_RE = re.compile(r'^lab_prefix="(?P<template>[^"]+)"$', re.MULTILINE)
_LAB_SUBNET_RE = re.compile(
    r"^INFINITO_SWARM_LAB_SUBNET=\$\{lab_prefix\}\.0/24$", re.MULTILINE
)


def _reserved_networks() -> dict[str, ipaddress.IPv4Network]:
    networks = load_yaml_any(str(_NETWORKS), default_if_missing={})
    reserved = {
        "NETWORK_TOR_VIRTUAL_CIDR": networks["NETWORK_TOR_VIRTUAL_CIDR"],
        "NETWORK_MESH_POOL": networks["NETWORK_MESH_POOL"],
    }
    for index, pool in enumerate(networks["NETWORK_DOCKER_ADDRESS_POOLS"]):
        reserved[f"NETWORK_DOCKER_ADDRESS_POOLS[{index}]"] = pool["base"]
    for index, pool in enumerate(networks["NETWORK_NESTED_DOCKER_ADDRESS_POOLS"]):
        reserved[f"NETWORK_NESTED_DOCKER_ADDRESS_POOLS[{index}]"] = pool["base"]
    reserved["NETWORK_NESTED_DOCKER_BIP"] = networks["NETWORK_NESTED_DOCKER_BIP"]
    reserved["primary INFINITO_SWARM_LAB_SUBNET"] = parse_static_env(
        PROJECT_ROOT / "default.env"
    )["INFINITO_SWARM_LAB_SUBNET"]
    reserved["worktree INFINITO_SUBNET range"] = "172.30.0.0/16"
    return {
        name: ipaddress.ip_network(value, strict=False)
        for name, value in reserved.items()
    }


class TestWorktreeSwarmLabSubnet(unittest.TestCase):
    def setUp(self) -> None:
        source = read_text(str(_UP_SH))
        max_slot = _MAX_SLOT_RE.search(source)
        lab_prefix = _LAB_PREFIX_RE.search(source)
        self.assertIsNotNone(max_slot, f"{_UP_SH} declares no max_slot")
        self.assertIsNotNone(lab_prefix, f"{_UP_SH} declares no lab_prefix")
        self.assertRegex(source, _LAB_SUBNET_RE)
        self.max_slot = int(max_slot.group("value"))
        self.template = lab_prefix.group("template")
        self.reserved = _reserved_networks()

    def _subnet(self, slot: int) -> ipaddress.IPv4Network:
        prefix = self.template.replace("${slot}", str(slot))
        return ipaddress.ip_network(f"{prefix}.0/24")

    def test_every_slot_pins_a_valid_distinct_unreserved_lab_subnet(self) -> None:
        seen: dict[ipaddress.IPv4Network, int] = {}
        for slot in range(1, self.max_slot + 1):
            with self.subTest(slot=slot):
                subnet = self._subnet(slot)
                clashes = sorted(
                    name for name, network in self.reserved.items() if subnet.overlaps(network)
                )
                self.assertEqual(clashes, [], f"slot {slot} lab {subnet} overlaps {clashes}")
                self.assertNotIn(subnet, seen, f"slot {slot} repeats slot {seen.get(subnet)}")
                seen[subnet] = slot


if __name__ == "__main__":
    unittest.main()
