import unittest

from plugins.filter.csp_filters import FilterModule


class TestCspFamilyAlignment(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "web-app-bigbluebutton": {
                "services": {
                    "matomo": {"enabled": True},
                    "logout": {"enabled": True},
                }
            },
            "web-app-dashboard": {"services": {"matomo": {"enabled": True}}},
        }
        self.domains = {
            "web-app-bigbluebutton": ["bbb.example.org"],
            "web-app-dashboard": ["dash.abc.onion"],
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example.org"],
            "web-app-matomo": ["matomo.abc.onion", "matomo.example.org"],
            "web-svc-logout": ["logout.abc.onion", "logout.example.org"],
            "web-app-keycloak": ["auth.abc.onion", "auth.example.org"],
        }

    def test_clearnet_consumer_gets_clearnet_provider_tokens(self):
        header = self.filter.build_csp_header(
            self.apps, "web-app-bigbluebutton", self.domains, "https"
        )
        self.assertIn("https://cdn.example.org", header)
        self.assertIn("https://matomo.example.org", header)
        self.assertIn("https://logout.example.org", header)
        self.assertIn("https://auth.example.org", header)
        self.assertNotIn("cdn.abc.onion", header)
        self.assertNotIn("matomo.abc.onion", header)
        self.assertNotIn("logout.abc.onion", header)
        self.assertNotIn("auth.abc.onion", header)

    def test_onion_consumer_keeps_onion_provider_tokens(self):
        header = self.filter.build_csp_header(
            self.apps, "web-app-dashboard", self.domains, "http"
        )
        self.assertIn("http://cdn.abc.onion", header)
        self.assertIn("http://matomo.abc.onion", header)
        self.assertNotIn("cdn.example.org", header)
        self.assertNotIn("matomo.example.org", header)

    def test_onion_only_provider_falls_back_for_clearnet_consumer(self):
        domains = dict(self.domains)
        domains["web-svc-cdn"] = ["cdn.abc.onion"]
        header = self.filter.build_csp_header(
            self.apps, "web-app-bigbluebutton", domains, "https"
        )
        self.assertIn("http://cdn.abc.onion", header)
        self.assertNotIn("https://cdn.abc.onion", header)

    def test_consumer_without_domains_entry_keeps_provider_primary(self):
        domains = dict(self.domains)
        del domains["web-app-bigbluebutton"]
        header = self.filter.build_csp_header(
            self.apps, "web-app-bigbluebutton", domains, "https"
        )
        self.assertIn("http://cdn.abc.onion", header)
        self.assertNotIn("https://cdn.abc.onion", header)
