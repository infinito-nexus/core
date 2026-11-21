import unittest
import unittest.mock as mock

from utils.networks import reachability
from utils.preflight.domains import clearnet_domains


class TestClearnetDomains(unittest.TestCase):
    def test_mappings_lists_and_strings_flatten(self):
        domains = [
            {"canonical": ["matomo.example.org"], "api": "api.example.org"},
            "example.org",
            [],
        ]
        self.assertEqual(
            clearnet_domains(domains),
            ["api.example.org", "example.org", "matomo.example.org"],
        )

    def test_onion_addresses_are_left_out(self):
        self.assertEqual(
            clearnet_domains(["abc.onion", "x.abc.onion", "example.org"]),
            ["example.org"],
        )

    def test_every_registry_network_but_clearnet_is_left_out(self):
        overlay = reachability.Network(
            "overlay", "overlay", None, ".overlay.test", False, False, 1
        )
        with mock.patch.dict(reachability.NETWORKS, {"overlay": overlay}):
            self.assertEqual(
                clearnet_domains(["wiki.overlay.test", "abc.onion", "example.org"]),
                ["example.org"],
            )

    def test_case_trailing_dots_and_duplicates_collapse(self):
        self.assertEqual(
            clearnet_domains(["Example.org.", "example.org", " "]), ["example.org"]
        )

    def test_non_domain_values_are_ignored(self):
        self.assertEqual(clearnet_domains([None, 5, True]), [])


if __name__ == "__main__":
    unittest.main()
