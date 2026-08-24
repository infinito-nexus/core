from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from plugins.lookup.redirect_uris import LookupModule, build_redirect_uris

SSO = {"services": {"sso": {"enabled": True}}}


class TestBuildRedirectUris(unittest.TestCase):
    def test_single_domain(self):
        result = build_redirect_uris({"app1": "example.org"}, {"app1": SSO}, True)
        self.assertEqual(result, ["https://example.org/*"])

    def test_multiple_domains(self):
        result = build_redirect_uris(
            {"appX": ["a.example.org", "b.example.org"]}, {"appX": SSO}, True
        )
        self.assertCountEqual(
            result, ["https://a.example.org/*", "https://b.example.org/*"]
        )

    def test_onion_domain_stays_plaintext(self):
        domains = {"clear": "app.example.org", "hidden": "abcdefghijklmnop.onion"}
        result = build_redirect_uris(domains, {"clear": SSO, "hidden": SSO}, True)
        self.assertCountEqual(
            result, ["https://app.example.org/*", "http://abcdefghijklmnop.onion/*"]
        )

    def test_per_app_tls_override_wins_over_the_global_default(self):
        domains = {"secure": "a.example.org", "plain": "b.example.org"}
        applications = {
            "secure": SSO,
            "plain": {**SSO, "server": {"tls": {"enabled": False}}},
        }
        result = build_redirect_uris(domains, applications, True)
        self.assertCountEqual(
            result, ["https://a.example.org/*", "http://b.example.org/*"]
        )

    def test_global_default_off_yields_plaintext(self):
        result = build_redirect_uris({"app1": "example.org"}, {"app1": SSO}, False)
        self.assertEqual(result, ["http://example.org/*"])

    def test_feature_missing_is_skipped(self):
        applications = {"app1": {"features": {"oauth2": False, "oidc": False}}}
        self.assertEqual(
            build_redirect_uris({"app1": "example.org"}, applications, True), []
        )

    def test_wildcard_customization(self):
        result = build_redirect_uris(
            {"app1": "x.test"}, {"app1": SSO}, False, wildcard="/cb"
        )
        self.assertEqual(result, ["http://x.test/cb"])

    def test_dedup_default_true(self):
        domains = {"app1": ["dup.test", "dup.test", "other.test"]}
        result = build_redirect_uris(domains, {"app1": SSO}, True)
        self.assertEqual(result, ["https://dup.test/*", "https://other.test/*"])

    def test_dedup_false_keeps_duplicates(self):
        domains = {"app1": ["dup.test", "dup.test"]}
        result = build_redirect_uris(domains, {"app1": SSO}, True, dedup=False)
        self.assertEqual(result, ["https://dup.test/*", "https://dup.test/*"])

    def test_nested_domain_mapping_is_flattened(self):
        domains = {
            "app1": {
                "primary": "a.example.org",
                "nested": {"x": "b.example.org", "y": ["c.example.org"]},
            }
        }
        result = build_redirect_uris(domains, {"app1": SSO}, True)
        self.assertEqual(
            result,
            [
                "https://a.example.org/*",
                "https://b.example.org/*",
                "https://c.example.org/*",
            ],
        )

    def test_invalid_domains_type_raises(self):
        with self.assertRaises(AnsibleError):
            build_redirect_uris(["not-a-dict"], {}, True)  # type: ignore[arg-type]

    def test_invalid_domain_value_raises(self):
        with self.assertRaises(AnsibleError):
            build_redirect_uris({"app1": 42}, {"app1": SSO}, True)


class TestRedirectUrisLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self.lookup._templar = None

    def test_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables={"TLS_ENABLED": True})

    def test_missing_tls_enabled_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={})


if __name__ == "__main__":
    unittest.main()
