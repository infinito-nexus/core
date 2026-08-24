import unittest

from plugins.filter.csp_filters import FilterModule


class TestAlignedSchemeTruthTable(unittest.TestCase):
    """Token scheme follows the ALIGNED provider host: onion => http, else the
    consumer protocol. One test per consumer-family x provider-family row."""

    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "web-app-bigbluebutton": {
                "services": {
                    "matomo": {"enabled": True},
                    "logout": {"enabled": True},
                }
            },
            "web-app-dashboard": {
                "services": {
                    "matomo": {"enabled": True},
                    "logout": {"enabled": True},
                }
            },
        }

    def _header(self, consumer, domains, protocol):
        return self.filter.build_csp_header(self.apps, consumer, domains, protocol)

    def test_clearnet_consumer_clearnet_only_providers(self):
        domains = {
            "web-app-bigbluebutton": ["bbb.example.org"],
            "web-svc-cdn": ["cdn.example.org"],
            "web-app-matomo": ["matomo.example.org"],
            "web-svc-logout": ["logout.example.org"],
            "web-app-keycloak": ["auth.example.org"],
        }
        header = self._header("web-app-bigbluebutton", domains, "https")
        self.assertIn("https://cdn.example.org", header)
        self.assertIn("https://matomo.example.org", header)
        self.assertNotIn(".onion", header)
        self.assertNotIn("http://cdn", header)

    def test_clearnet_consumer_dual_providers_gets_clearnet_https(self):
        domains = {
            "web-app-bigbluebutton": ["bbb.example.org"],
            "web-svc-cdn": ["cdn.abc.onion", "cdn.example.org"],
            "web-app-matomo": ["matomo.abc.onion", "matomo.example.org"],
            "web-svc-logout": ["logout.abc.onion", "logout.example.org"],
            "web-app-keycloak": ["auth.abc.onion", "auth.example.org"],
        }
        header = self._header("web-app-bigbluebutton", domains, "https")
        self.assertIn("https://cdn.example.org", header)
        self.assertIn("https://matomo.example.org", header)
        self.assertNotIn("cdn.abc.onion", header)
        self.assertNotIn("matomo.abc.onion", header)

    def test_clearnet_consumer_onion_only_providers_gets_http_onion(self):
        domains = {
            "web-app-bigbluebutton": ["bbb.example.org"],
            "web-svc-cdn": ["cdn.abc.onion"],
            "web-app-matomo": ["matomo.abc.onion"],
            "web-svc-logout": ["logout.abc.onion"],
            "web-app-keycloak": ["auth.abc.onion"],
        }
        header = self._header("web-app-bigbluebutton", domains, "https")
        self.assertIn("http://cdn.abc.onion", header)
        self.assertIn("http://matomo.abc.onion", header)
        self.assertNotIn("https://cdn.abc.onion", header)
        self.assertNotIn("https://matomo.abc.onion", header)
        self.assertNotIn("https://logout.abc.onion", header)
        self.assertNotIn("https://auth.abc.onion", header)

    def test_onion_consumer_onion_providers_unchanged(self):
        domains = {
            "web-app-dashboard": ["dash.abc.onion"],
            "web-svc-cdn": ["cdn.abc.onion"],
            "web-app-matomo": ["matomo.abc.onion"],
            "web-svc-logout": ["logout.abc.onion"],
            "web-app-keycloak": ["auth.abc.onion"],
        }
        header = self._header("web-app-dashboard", domains, "http")
        self.assertIn("http://cdn.abc.onion", header)
        self.assertIn("http://matomo.abc.onion", header)
        self.assertNotIn("https://", header)

    def test_onion_consumer_clearnet_only_provider_keeps_consumer_scheme(self):
        domains = {
            "web-app-dashboard": ["dash.abc.onion"],
            "web-svc-cdn": ["cdn.example.org"],
            "web-app-matomo": ["matomo.example.org"],
            "web-svc-logout": ["logout.example.org"],
            "web-app-keycloak": ["auth.example.org"],
        }
        header = self._header("web-app-dashboard", domains, "http")
        self.assertIn("http://cdn.example.org", header)
        self.assertIn("http://matomo.example.org", header)


if __name__ == "__main__":
    unittest.main()
