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

from generate.all_domains import FilterModule


class TestGenerateAllDomains(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule().generate_all_domains

    def test_simple_string_values(self):
        domains = {"app": "example.com"}
        result = self.filter(domains)
        expected = ["example.com", "www.example.com"]
        self.assertEqual(result, expected)

    def test_list_and_dict_values(self):
        domains = {"app1": ["one.com", "two.com"], "app2": {"x": "x.com", "y": "y.com"}}
        result = self.filter(domains)
        expected = sorted(
            [
                "one.com",
                "two.com",
                "x.com",
                "y.com",
                "www.one.com",
                "www.two.com",
                "www.x.com",
                "www.y.com",
            ]
        )
        self.assertEqual(result, expected)

    def test_include_www_false(self):
        domains = {"app": "no-www.com"}
        result = self.filter(domains, include_www=False)
        self.assertEqual(result, ["no-www.com"])

    def test_deduplicate_and_sort(self):
        domains = {
            "a": "dup.com",
            "b": "dup.com",
            "c": ["b.com", "a.com"],
        }
        result = self.filter(domains)
        expected = [
            "a.com",
            "b.com",
            "dup.com",
            "www.a.com",
            "www.b.com",
            "www.dup.com",
        ]
        self.assertEqual(result, expected)
