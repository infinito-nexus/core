"""The cert lookup plans the certificate of every name an application serves."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from plugins.lookup.cert import LookupModule
from utils.tests.caches import reset_caches

APP = "web-app-wordpress"
WILDCARD = "*.user.blog.main.test"
BIBER = "biber.user.blog.main.test"
LIVE = "/etc/letsencrypt/live/"
SELFSIGNED = "/etc/infinito.nexus/selfsigned"


class TestCertServedNames(unittest.TestCase):
    def setUp(self):
        reset_caches(files_changed=False)
        self.lookup = LookupModule()
        self.lookup._loader = mock.MagicMock()
        self.vars = {
            "domains": {APP: ["blog.main.test"]},
            "applications": {APP: {}},
            "TLS_ENABLED": True,
            "TLS_MODE": "letsencrypt",
            "CERTBOT_FLAVOR": "dedicated",
            "LETSENCRYPT_LIVE_PATH": LIVE,
            "TLS_SELFSIGNED_BASE_PATH": SELFSIGNED,
            "TLS_SELFSIGNED_SCOPE": "global",
            "CURRENT_PLAY_DOMAINS_ALL": ["blog.main.test", WILDCARD],
            "CURRENT_PLAY_SERVED_DOMAINS": [
                {"name": WILDCARD, "application_id": APP, "hosts": [BIBER]}
            ],
        }

        def _get(name, *_args, **_kwargs):
            return mock.MagicMock(
                run=lambda _terms, variables=None, **_kw: [(variables or {})[name]]
            )

        loader_patcher = mock.patch("plugins.lookup.cert.lookup_loader")
        loader_patcher.start().get.side_effect = _get
        self.addCleanup(loader_patcher.stop)

    def tearDown(self):
        reset_caches(files_changed=False)

    def _plan(self, term, **overrides):
        return self.lookup.run([term], variables=dict(self.vars, **overrides))[0]

    def test_every_flavor_keeps_the_served_wildcard_in_a_lineage_of_its_own(self):
        for flavor in ("san", "dedicated", "wildcard"):
            with self.subTest(flavor=flavor):
                plan = self._plan(WILDCARD, CERTBOT_FLAVOR=flavor)
                self.assertEqual(APP, plan["application_id"])
                self.assertEqual(WILDCARD, plan["cert_id"])
                self.assertEqual(
                    f"{LIVE}{WILDCARD}/fullchain.pem", plan["files"]["cert"]
                )

    def test_a_served_member_host_keeps_a_lineage_of_its_own(self):
        variables = {
            "CURRENT_PLAY_SERVED_DOMAINS": [
                {"name": BIBER, "application_id": APP, "hosts": [BIBER]}
            ],
            "CURRENT_PLAY_DOMAINS_ALL": ["blog.main.test", BIBER],
        }
        plan = self._plan(BIBER, **variables)
        self.assertEqual(APP, plan["application_id"])
        self.assertEqual(f"{LIVE}{BIBER}/fullchain.pem", plan["files"]["cert"])

    def test_every_named_term_keeps_the_lineage_certbot_names_after_it(self):
        variables = {
            "applications": {APP: {"domains": {"aliases": ["alias.main.test"]}}},
            "CURRENT_PLAY_REDIRECT_DOMAINS": [
                {"source": "legacy.main.test", "target": "blog.main.test"}
            ],
        }
        terms = ("blog.main.test", "alias.main.test", "legacy.main.test")
        for flavor in ("san", "dedicated"):
            for term in (*terms, "www.blog.main.test"):
                with self.subTest(flavor=flavor, term=term):
                    plan = self._plan(term, CERTBOT_FLAVOR=flavor, **variables)
                    self.assertEqual(APP, plan["application_id"])
                    self.assertEqual(term, plan["cert_id"])
                    cert = plan["files"]["cert"]
                    self.assertEqual(f"{LIVE}{term}/fullchain.pem", cert)

    def test_the_global_self_signed_certificate_carries_the_served_wildcard(self):
        plan = self._plan(WILDCARD, TLS_MODE="self_signed")
        self.assertEqual(f"{SELFSIGNED}/global/fullchain.pem", plan["files"]["cert"])
        self.assertIn(WILDCARD, plan["domains"]["san"])

    def test_an_app_scoped_certificate_carries_the_served_names_on_every_vhost(self):
        sans = {
            term: self._plan(term, TLS_MODE="self_signed", TLS_SELFSIGNED_SCOPE="app")
            for term in ("blog.main.test", WILDCARD)
        }
        self.assertEqual(
            sans["blog.main.test"]["files"]["cert"], sans[WILDCARD]["files"]["cert"]
        )
        for term, plan in sans.items():
            with self.subTest(term=term):
                self.assertEqual(
                    sorted(["blog.main.test", WILDCARD]),
                    sorted(plan["domains"]["san"]),
                )


if __name__ == "__main__":
    unittest.main()
