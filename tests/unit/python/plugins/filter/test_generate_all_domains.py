import unittest

from plugins.filter.generate.all_domains import FilterModule


class TestGenerateAllDomains(unittest.TestCase):
    def setUp(self):
        self.plugin = FilterModule().filters()["generate_all_domains"]

    def test_flattens_str_list_and_dict(self):
        domains_dict = {
            "web-app-simple": ["simple.example"],
            "web-app-matrix": {
                "synapse": "matrix.example",
                "element": "element.example",
            },
            "svc-prx-openresty": {"canonical": ["example"]},
        }

        result = self.plugin(domains_dict, include_www=False)

        expected = sorted(
            [
                "simple.example",
                "matrix.example",
                "element.example",
                "example",
            ]
        )

        self.assertEqual(result, expected)

    def test_includes_www_and_dedupes(self):
        domains_dict = {
            "a": ["alpha.example", "beta.example"],
            "b": {"x": "alpha.example"},
            "c": {"canonical": ["beta.example"]},
        }

        result = self.plugin(domains_dict, include_www=True)

        expected = sorted(
            {
                "alpha.example",
                "beta.example",
                "www.alpha.example",
                "www.beta.example",
            }
        )

        self.assertEqual(result, expected)

    def test_ignores_none_and_unsupported_types(self):
        class Weird:
            pass

        domains_dict = {
            "ok": ["ok.example"],
            "none": None,
            "weird": Weird(),
            "nested": {
                "x": None,
                "y": ["y.example"],
                "z": {"deep": "deep.example"},
            },
        }

        result = self.plugin(domains_dict, include_www=False)

        expected = sorted(
            [
                "ok.example",
                "y.example",
                "deep.example",
            ]
        )

        self.assertEqual(result, expected)

    def test_empty_input(self):
        self.assertEqual(self.plugin({}, include_www=False), [])
        self.assertEqual(self.plugin(None, include_www=False), [])


if __name__ == "__main__":
    unittest.main()
