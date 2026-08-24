import unittest

from plugins.filter.cookie_scope import common_dns_suffix, domain_strings
from utils.cache.files import PROJECT_ROOT, read_text


class CommonDnsSuffixTests(unittest.TestCase):
    def test_sso_template_normalizes_mapping_before_filtering(self):
        template = read_text(
            str(
                PROJECT_ROOT
                / "roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2"
            )
        )

        normalization = "| domain_strings"
        self.assertIn(normalization, template)
        self.assertLess(
            template.index(normalization), template.index("select('search'")
        )
        self.assertLess(
            template.index(normalization), template.index("reject('search'")
        )

    def test_domain_pipeline_normalizes_every_supported_shape(self):
        mapping = {
            "filer": "filer.seaweedfs.s3.infinito.example",
            "master": "master.seaweedfs.s3.infinito.example",
        }
        self.assertEqual(
            common_dns_suffix(domain_strings(mapping)),
            "seaweedfs.s3.infinito.example",
        )
        self.assertEqual(
            common_dns_suffix(domain_strings("cloud.infinito.example")),
            "cloud.infinito.example",
        )
        mixed = domain_strings(
            ["cloud.infinito.example", "cloud.examplelongonionaddress.onion"]
        )
        clearnet = [domain for domain in mixed if not domain.endswith(".onion")]
        self.assertEqual(common_dns_suffix(clearnet), "cloud.infinito.example")

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
