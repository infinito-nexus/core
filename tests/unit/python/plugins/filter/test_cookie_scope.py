import unittest

from plugins.filter.cookie_scope import common_dns_suffix, domain_strings
from utils.domains.default_primary import default_domain_primary

DOMAIN = default_domain_primary()


class CommonDnsSuffixTests(unittest.TestCase):
    def test_domain_pipeline_normalizes_every_supported_shape(self):
        mapping = {
            "filer": f"filer.seaweedfs.s3.{DOMAIN}",
            "master": f"master.seaweedfs.s3.{DOMAIN}",
        }
        self.assertEqual(
            common_dns_suffix(domain_strings(mapping)),
            f"seaweedfs.s3.{DOMAIN}",
        )
        self.assertEqual(
            common_dns_suffix(domain_strings(f"cloud.{DOMAIN}")),
            f"cloud.{DOMAIN}",
        )
        mixed = domain_strings(
            [f"cloud.{DOMAIN}", "cloud.examplelongonionaddress.onion"]
        )
        clearnet = [domain for domain in mixed if not domain.endswith(".onion")]
        self.assertEqual(common_dns_suffix(clearnet), f"cloud.{DOMAIN}")

    def test_single_domain_returned_unchanged(self):
        self.assertEqual(common_dns_suffix([f"cloud.{DOMAIN}"]), f"cloud.{DOMAIN}")

    def test_multi_domain_collapses_to_shared_parent(self):
        self.assertEqual(
            common_dns_suffix(
                [
                    f"api.seaweedfs.s3.{DOMAIN}",
                    f"filer.seaweedfs.s3.{DOMAIN}",
                    f"master.seaweedfs.s3.{DOMAIN}",
                ]
            ),
            f"seaweedfs.s3.{DOMAIN}",
        )

    def test_subdomain_alias_keeps_minimal_shared_suffix(self):
        self.assertEqual(
            common_dns_suffix([f"app.{DOMAIN}", f"www.app.{DOMAIN}"]),
            f"app.{DOMAIN}",
        )

    def test_dict_input_uses_values_multi(self):
        self.assertEqual(
            common_dns_suffix(
                {
                    "filer": f"filer.seaweedfs.s3.{DOMAIN}",
                    "master": f"master.seaweedfs.s3.{DOMAIN}",
                    "api": f"api.seaweedfs.s3.{DOMAIN}",
                }
            ),
            f"seaweedfs.s3.{DOMAIN}",
        )

    def test_dict_input_single_value(self):
        self.assertEqual(
            common_dns_suffix({"web": f"cloud.{DOMAIN}"}),
            f"cloud.{DOMAIN}",
        )

    def test_string_input(self):
        self.assertEqual(common_dns_suffix(f"cloud.{DOMAIN}"), f"cloud.{DOMAIN}")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(common_dns_suffix([]), "")
        self.assertEqual(common_dns_suffix(None), "")

    def test_blank_entries_ignored(self):
        self.assertEqual(common_dns_suffix(["", f"cloud.{DOMAIN}"]), f"cloud.{DOMAIN}")


if __name__ == "__main__":
    unittest.main()
