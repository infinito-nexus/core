"""Per: subnets declared per-role under
``meta/networks.yml.local.subnet`` and ``overlay.stream_relay.subnet`` MUST
be valid, unique, and non-overlapping across the role tree."""

from __future__ import annotations

import ipaddress
import unittest

from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_subnets
from utils.networks.attachments import STREAM_RELAY
from utils.roles.mapping import ROLE_FILE_META_NETWORKS


class TestNetworksUniqueValidAndMapped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.repo_root = str(PROJECT_ROOT)
        cls.roles_dir = PROJECT_ROOT / "roles"

        cls.role_to_subnet: dict[str, ipaddress.IPv4Network] = {}
        for role_path in sorted(cls.roles_dir.iterdir()):
            if not role_path.is_dir():
                continue
            networks_file = role_path / ROLE_FILE_META_NETWORKS
            if not networks_file.is_file():
                continue
            networks_data = load_yaml_any(str(networks_file)) or {}
            overlay = networks_data.get("overlay")
            relay = overlay.get(STREAM_RELAY) if isinstance(overlay, dict) else None
            pinned = (
                (role_path.name, networks_data.get("local")),
                (f"{role_path.name}:{STREAM_RELAY}", relay),
            )
            for owner, block in pinned:
                if not isinstance(block, dict):
                    continue
                subnet = block.get("subnet")
                if not isinstance(subnet, str):
                    continue
                try:
                    cls.role_to_subnet[owner] = ipaddress.IPv4Network(subnet.strip())
                except (ValueError, ipaddress.AddressValueError) as exc:
                    raise AssertionError(
                        f"Invalid subnet for '{owner}': {subnet!r} ({exc})"
                    ) from exc

    def test_a_stream_relay_subnet_is_checked_and_allocated_like_a_role_subnet(self):
        owner = f"svc-db-openldap:{STREAM_RELAY}"
        self.assertIn(owner, self.role_to_subnet)
        self.assertEqual(dict(iter_subnets())[owner], self.role_to_subnet[owner])

    def test_unique_subnets(self):
        seen: dict[ipaddress.IPv4Network, str] = {}
        dupes: list[str] = []
        for role, net in self.role_to_subnet.items():
            if net in seen:
                dupes.append(f"{seen[net]} and {role} both use {net}")
            else:
                seen[net] = role
        if dupes:
            self.fail(
                "Duplicate subnets detected:\n"
                + "\n".join(dupes)
                + "\n\nFix: pick a free subnet via "
                + "`infinito meta networks suggest --clients <N> --count 1` "
                + "and update the role's meta/networks.yml.local.subnet."
            )

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
            self.fail(
                "Subnet overlaps detected:\n"
                + "\n".join(overlaps)
                + "\n\nFix: pick a free subnet via "
                + "`infinito meta networks suggest --clients <N> --count 1` "
                + "and update the role's meta/networks.yml.local.subnet."
            )


if __name__ == "__main__":
    unittest.main()
