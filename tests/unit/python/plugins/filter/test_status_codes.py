import unittest

from plugins.filter.status_codes import FilterModule
from utils.roles.applications.status_codes import (
    DEFAULT_OK,
    accepted_status_codes,
    declared_status_codes,
)

SEAWEEDFS = {
    "web-app-seaweedfs": {
        "domains": {
            "canonical": {
                "api": "s3.example.org",
                "filer": "filer.example.org",
                "master": "master.example.org",
            }
        },
        "server": {
            "status_codes": {
                "api": [301, 302, 403, 405],
                "filer": [302, 403],
                "master": [302, 403],
            }
        },
    }
}


class TestDeclaredStatusCodes(unittest.TestCase):
    def test_per_vhost_key_wins(self):
        for domain, codes in (
            ("s3.example.org", [301, 302, 403, 405]),
            ("filer.example.org", [302, 403]),
            ("master.example.org", [302, 403]),
        ):
            with self.subTest(domain=domain):
                self.assertEqual(
                    declared_status_codes(SEAWEEDFS, "web-app-seaweedfs", domain),
                    codes,
                )

    def test_undeclared_app_declares_nothing(self):
        apps = {"web-app-plain": {"domains": {"canonical": ["plain.example.org"]}}}
        self.assertEqual(
            declared_status_codes(apps, "web-app-plain", "plain.example.org"), []
        )

    def test_flat_canonical_uses_the_default_key(self):
        apps = {
            "web-app-prometheus": {
                "domains": {"canonical": ["metrics.example.org"]},
                "server": {"status_codes": {"default": [405]}},
            }
        }
        self.assertEqual(
            declared_status_codes(apps, "web-app-prometheus", "metrics.example.org"),
            [405],
        )

    def test_unknown_domain_falls_back_to_the_declared_default(self):
        apps = {
            "web-app-x": {
                "domains": {"canonical": {"api": "api.example.org"}},
                "server": {"status_codes": {"api": [403], "default": [404]}},
            }
        }
        self.assertEqual(
            declared_status_codes(apps, "web-app-x", "other.example.org"), [404]
        )

    def test_a_key_without_its_own_codes_uses_the_default(self):
        apps = {
            "web-app-x": {
                "domains": {"canonical": {"api": "api.example.org"}},
                "server": {"status_codes": {"other": [403], "default": [404]}},
            }
        }
        self.assertEqual(
            declared_status_codes(apps, "web-app-x", "api.example.org"), [404]
        )

    def test_scalar_and_string_codes_are_normalized(self):
        apps = {
            "web-app-x": {
                "domains": {"canonical": {"api": ["api.example.org"]}},
                "server": {"status_codes": {"api": "403"}},
            }
        }
        self.assertEqual(
            declared_status_codes(apps, "web-app-x", "api.example.org"), [403]
        )

    def test_out_of_range_declarations_are_dropped(self):
        apps = {
            "web-app-x": {
                "domains": {"canonical": {"api": "api.example.org"}},
                "server": {"status_codes": {"api": [999, "nope"]}},
            }
        }
        self.assertEqual(
            declared_status_codes(apps, "web-app-x", "api.example.org"), []
        )


class TestAcceptedStatusCodes(unittest.TestCase):
    def test_filter_is_registered(self):
        self.assertIn("accepted_status_codes", FilterModule().filters())

    def test_declared_codes_are_added_to_the_default(self):
        self.assertEqual(
            accepted_status_codes(SEAWEEDFS, "web-app-seaweedfs", "filer.example.org"),
            [200, 302, 301, 403],
        )

    def test_a_narrower_declaration_never_narrows_the_gate(self):
        apps = {
            "web-app-mailu": {
                "domains": {"canonical": ["mail.example.org"]},
                "server": {"status_codes": {"default": [200, 301]}},
            }
        }
        self.assertEqual(
            accepted_status_codes(apps, "web-app-mailu", "mail.example.org"),
            DEFAULT_OK,
        )

    def test_a_disjoint_declaration_only_adds(self):
        apps = {
            "web-svc-mirror": {
                "domains": {"canonical": ["mirror.example.org"]},
                "server": {"status_codes": {"default": [404]}},
            }
        }
        self.assertEqual(
            accepted_status_codes(apps, "web-svc-mirror", "mirror.example.org"),
            [200, 302, 301, 404],
        )

    def test_undeclared_app_gets_the_default(self):
        apps = {"web-app-plain": {"domains": {"canonical": ["plain.example.org"]}}}
        self.assertEqual(
            accepted_status_codes(apps, "web-app-plain", "plain.example.org"),
            DEFAULT_OK,
        )

    def test_the_result_is_a_copy(self):
        first = accepted_status_codes(SEAWEEDFS, "web-app-seaweedfs", "unknown.org")
        first.append(418)
        self.assertEqual(
            accepted_status_codes(SEAWEEDFS, "web-app-seaweedfs", "unknown.org"),
            DEFAULT_OK,
        )


if __name__ == "__main__":
    unittest.main()
