from __future__ import annotations

import unittest

from ansible.errors import AnsibleError

from utils.tls.common import resolve_term, wildcard_certificate_available

APP = "web-app-wordpress"
DOMAINS = {APP: ["blog.main.test"], "web-app-other": ["other.main.test"]}
SERVED = {"*.user.blog.main.test": APP, "biber.user.blog.main.test": APP}
LETSENCRYPT = {"TLS_ENABLED": True, "TLS_MODE": "letsencrypt"}


def _resolve(term, served=SERVED):
    return resolve_term(
        term,
        domains=DOMAINS,
        applications={},
        redirects={},
        served=served,
        forced_mode="auto",
        err_prefix="test",
    )


class TestWildcardCertificateAvailable(unittest.TestCase):
    def test_a_host_without_tls_serves_any_wildcard(self):
        variables = {"TLS_ENABLED": False, "TLS_MODE": "letsencrypt"}
        self.assertTrue(wildcard_certificate_available({}, variables))

    def test_a_self_signed_certificate_carries_any_wildcard(self):
        variables = {"TLS_ENABLED": True, "TLS_MODE": "self_signed"}
        self.assertTrue(wildcard_certificate_available({}, variables))

    def test_the_application_tls_override_decides_over_the_host(self):
        webroot = dict(
            LETSENCRYPT,
            CERTBOT_FLAVOR="dedicated",
            CERTBOT_ACME_CHALLENGE_METHOD="webroot",
        )
        for app, expected in (
            ({}, False),
            ({"server": {"tls": {"enabled": False}}}, True),
            ({"server": {"tls": {"flavor": "self_signed"}}}, True),
        ):
            with self.subTest(app=app):
                self.assertIs(expected, wildcard_certificate_available(app, webroot))

    def test_letsencrypt_proves_a_wildcard_only_with_the_wildcard_flavor_over_dns(self):
        for flavor, challenge, expected in (
            ("wildcard", "cloudflare", True),
            ("wildcard", "hetzner", True),
            ("wildcard", "webroot", False),
            ("dedicated", "cloudflare", False),
            ("san", "cloudflare", False),
            ("dedicated", "webroot", False),
        ):
            variables = dict(
                LETSENCRYPT,
                CERTBOT_FLAVOR=flavor,
                CERTBOT_ACME_CHALLENGE_METHOD=challenge,
            )
            with self.subTest(flavor=flavor, challenge=challenge):
                self.assertIs(expected, wildcard_certificate_available({}, variables))

    def test_letsencrypt_without_its_settings_fails(self):
        with self.assertRaises(AnsibleError):
            wildcard_certificate_available({}, LETSENCRYPT)

    def test_an_unknown_mode_fails(self):
        variables = {"TLS_ENABLED": True, "TLS_MODE": "acme"}
        with self.assertRaises(AnsibleError):
            wildcard_certificate_available({}, variables)


class TestResolveServedName(unittest.TestCase):
    def test_a_served_name_resolves_to_its_owner_as_its_own_primary(self):
        for name in ("*.user.blog.main.test", "Biber.User.Blog.Main.Test"):
            with self.subTest(name=name):
                self.assertEqual((APP, name.lower()), _resolve(name))

    def test_a_canonical_domain_still_resolves_through_the_domain_map(self):
        self.assertEqual(
            ("web-app-other", "other.main.test"), _resolve("other.main.test")
        )

    def test_a_name_neither_canonical_nor_served_fails(self):
        with self.assertRaises(AnsibleError):
            _resolve("alice.user.blog.main.test")

    def test_a_served_name_is_unknown_without_the_served_map(self):
        with self.assertRaises(AnsibleError):
            _resolve("*.user.blog.main.test", served={})


if __name__ == "__main__":
    unittest.main()
