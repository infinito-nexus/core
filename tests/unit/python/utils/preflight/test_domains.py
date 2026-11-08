import unittest

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

    def test_case_trailing_dots_and_duplicates_collapse(self):
        self.assertEqual(
            clearnet_domains(["Example.org.", "example.org", " "]), ["example.org"]
        )

    def test_non_domain_values_are_ignored(self):
        self.assertEqual(clearnet_domains([None, 5, True]), [])


if __name__ == "__main__":
    unittest.main()
