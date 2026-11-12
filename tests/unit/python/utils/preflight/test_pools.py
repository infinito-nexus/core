import unittest

from utils.preflight.pools import address_pool_errors

RESERVED = [
    ("NETWORK_MESH_POOL reserves", "10.100.0.0/16"),
    ("NETWORK_TOR_VIRTUAL_CIDR reserves", "10.240.0.0/12"),
    ("web-app-matomo declares for its network 'matomo'", "192.168.31.0/24"),
]


class TestAddressPoolErrors(unittest.TestCase):
    def test_the_shipped_pool_is_clear(self):
        config = {"default-address-pools": [{"base": "10.208.0.0/12", "size": 24}]}
        self.assertEqual(address_pool_errors(config, RESERVED), [])

    def test_an_absent_file_or_key_has_nothing_to_compare(self):
        self.assertEqual(address_pool_errors({}, RESERVED), [])
        self.assertEqual(address_pool_errors({"dns": ["192.0.2.53"]}, RESERVED), [])

    def test_a_pool_over_a_role_subnet_and_the_mesh_names_both(self):
        config = {
            "default-address-pools": [
                {"base": "192.168.0.0/16", "size": 20},
                {"base": "10.0.0.0/8", "size": 24},
            ]
        }
        self.assertEqual(
            address_pool_errors(config, RESERVED),
            [
                (
                    "docker default address pool 192.168.0.0/16 overlaps 192.168.31.0/24, "
                    "which web-app-matomo declares for its network 'matomo'"
                ),
                (
                    "docker default address pool 10.0.0.0/8 overlaps 10.100.0.0/16, "
                    "which NETWORK_MESH_POOL reserves"
                ),
                (
                    "docker default address pool 10.0.0.0/8 overlaps 10.240.0.0/12, "
                    "which NETWORK_TOR_VIRTUAL_CIDR reserves"
                ),
            ],
        )

    def test_an_ipv6_pool_never_overlaps_an_ipv4_range(self):
        config = {"default-address-pools": [{"base": "fd00::/48", "size": 64}]}
        self.assertEqual(address_pool_errors(config, RESERVED), [])

    def test_a_pool_without_a_base_is_rejected(self):
        with self.assertRaises(ValueError):
            address_pool_errors({"default-address-pools": [{"size": 24}]}, RESERVED)


if __name__ == "__main__":
    unittest.main()
