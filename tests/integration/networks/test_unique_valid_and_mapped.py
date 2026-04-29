"""Per req-009: subnets declared per-role under
``meta/server.yml.networks.local.subnet`` MUST be valid, unique, and
non-overlapping across the role tree."""

from __future__ import annotations

import glob
import ipaddress
import os
import unittest

import yaml


class TestNetworksUniqueValidAndMapped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(__file__)
        cls.repo_root = os.path.abspath(os.path.join(base_dir, "..", "..", ".."))
        cls.roles_dir = os.path.join(cls.repo_root, "roles")

        cls.role_to_subnet: dict[str, ipaddress.IPv4Network] = {}
        for role_path in sorted(glob.glob(os.path.join(cls.roles_dir, "*"))):
            if not os.path.isdir(role_path):
                continue
            server_file = os.path.join(role_path, "meta", "server.yml")
            if not os.path.isfile(server_file):
                continue
            with open(server_file, "r", encoding="utf-8") as f:
                server_data = yaml.safe_load(f) or {}
            networks = server_data.get("networks") or {}
            if not isinstance(networks, dict):
                continue
            local = networks.get("local")
            if not isinstance(local, dict):
                continue
            subnet = local.get("subnet")
            if not isinstance(subnet, str):
                continue
            try:
                cls.role_to_subnet[os.path.basename(role_path)] = ipaddress.IPv4Network(
                    subnet.strip()
                )
            except (ValueError, ipaddress.AddressValueError) as exc:
                raise AssertionError(
                    f"Invalid subnet for role '{os.path.basename(role_path)}': "
                    f"{subnet!r} ({exc})"
                ) from exc

    def test_unique_subnets(self):
        seen: dict[ipaddress.IPv4Network, str] = {}
        dupes: list[str] = []
        for role, net in self.role_to_subnet.items():
            if net in seen:
                dupes.append(f"{seen[net]} and {role} both use {net}")
            else:
                seen[net] = role
        if dupes:
            self.fail("Duplicate subnets detected:\n" + "\n".join(dupes))

    def test_no_overlapping_subnets(self):
        items = list(self.role_to_subnet.items())
        overlaps: list[str] = []
        for i in range(len(items)):
            name1, net1 = items[i]
            for j in range(i + 1, len(items)):
                name2, net2 = items[j]
                if net1.overlaps(net2):
                    overlaps.append(f"'{name1}' ({net1}) overlaps '{name2}' ({net2})")
        if overlaps:
            self.fail("Subnet overlaps detected:\n" + "\n".join(overlaps))


if __name__ == "__main__":
    unittest.main()
