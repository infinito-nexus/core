import unittest

from plugins.filter.cookie_scope import common_dns_suffix


class CommonDnsSuffixTests(unittest.TestCase):
    def test_single_domain_returned_unchanged(self):
        self.assertEqual(
            common_dns_suffix(["cloud.infinito.example"]), "cloud.infinito.example"
        )

    def test_multi_domain_collapses_to_shared_parent(self):
        self.assertEqual(
            common_dns_suffix(
                [
                    "api.seaweedfs.s3.infinito.example",
                    "filer.seaweedfs.s3.infinito.example",
                    "master.seaweedfs.s3.infinito.example",
                ]
            ),
            "seaweedfs.s3.infinito.example",
        )

    def test_subdomain_alias_keeps_minimal_shared_suffix(self):
        self.assertEqual(
            common_dns_suffix(["app.infinito.example", "www.app.infinito.example"]),
            "app.infinito.example",
        )

    def test_dict_input_uses_values_multi(self):
        self.assertEqual(
            common_dns_suffix(
                {
                    "filer": "filer.seaweedfs.s3.infinito.example",
                    "master": "master.seaweedfs.s3.infinito.example",
                    "api": "api.seaweedfs.s3.infinito.example",
                }
            ),
            "seaweedfs.s3.infinito.example",
        )

    def test_dict_input_single_value(self):
        self.assertEqual(
            common_dns_suffix({"web": "cloud.infinito.example"}),
            "cloud.infinito.example",
        )

    def test_string_input(self):
        self.assertEqual(
            common_dns_suffix("cloud.infinito.example"), "cloud.infinito.example"
        )

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(common_dns_suffix([]), "")
        self.assertEqual(common_dns_suffix(None), "")

    def test_blank_entries_ignored(self):
        self.assertEqual(
            common_dns_suffix(["", "cloud.infinito.example"]), "cloud.infinito.example"
        )


if __name__ == "__main__":
    unittest.main()
