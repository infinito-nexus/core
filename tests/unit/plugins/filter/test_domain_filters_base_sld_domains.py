import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(
            str(Path(str(Path(__file__).parent)) / "../../../../plugins/filter")
        ).resolve()
    ),
)

from ansible.errors import AnsibleFilterError
from generate.base_sld_domains import FilterModule


class TestGenerateBaseSldDomains(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule().generate_base_sld_domains

    def test_simple_list(self):
        domains = ["sub.example.com", "alias.example.com", "example.com"]
        result = self.filter(domains)
        self.assertEqual(result, ["example.com"])

    def test_mixed_tlds_and_subdomains(self):
        domains = ["a.co", "b.co", "sub.b.co", "x.co", "www.x.co"]
        result = self.filter(domains)
        self.assertEqual(result, ["a.co", "b.co", "x.co"])

    def test_invalid_non_string_raise(self):
        for bad in [42, None]:
            with self.assertRaises(AnsibleFilterError):
                self.filter([bad])

    def test_localhost_allowed(self):
        domains = ["localhost"]
        result = self.filter(domains)
        self.assertEqual(result, ["localhost"])

    def test_ip_raises(self):
        with self.assertRaises(AnsibleFilterError):
            self.filter(["127.0.0.1"])

    def test_nested_subdomains(self):
        domains = ["sub.sub2.one"]
        result = self.filter(domains)
        self.assertEqual(result, ["sub2.one"])

    def test_deeply_nested_subdomains(self):
        domains = ["sub3.sub2.sub1.one"]
        result = self.filter(domains)
        self.assertEqual(result, ["sub1.one"])

    def test_empty_and_malformed_raise(self):
        for bad in ["", ".", "..."]:
            with self.assertRaises(AnsibleFilterError):
                self.filter([bad])

    def test_sorting_and_duplicates(self):
        domains = ["one.com", "sub.one.com", "two.com", "deep.two.com", "one.com"]
        result = self.filter(domains)
        self.assertEqual(result, ["one.com", "two.com"])


if __name__ == "__main__":
    unittest.main()
