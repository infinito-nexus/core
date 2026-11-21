"""Every deployment host a vhost's CSP names lies in that vhost's network,
except the one SSO issuer."""

import unittest

from plugins.filter.csp_filters import FilterModule
from utils.domains.default_primary import default_domain_primary
from utils.networks.reachability import CLEARNET, TOR, network_of

NODE = "ndck3kzcxbcem2oskbhytxwevvpzwn7j5dj6q36vbijyrnw3rjf2heqd.onion"
PRIMARY = default_domain_primary()
ISSUER = f"auth.{PRIMARY}"
PROVIDERS = {
    "web-svc-cdn": "cdn",
    "web-svc-mirror": "mirror",
    "web-app-matomo": "matomo",
    "web-svc-simpleicons": "icons",
    "web-svc-api": "api",
    "web-app-dashboard": "dashboard",
    "web-svc-logout": "logout",
    "web-app-keycloak": "auth",
    "app1": "app1",
}
FEATURES = ("tor", "matomo", "simpleicons", "api", "dashboard", "logout")


def _hosts(header: str) -> set[str]:
    hosts = set()
    for token in header.replace(";", " ").split():
        if token.startswith("'") or "." not in token:
            continue
        host = token.split("://", 1)[-1].split("/", 1)[0]
        hosts.add(host.removeprefix("*."))
    return hosts


class TestCspVhostNetwork(unittest.TestCase):
    def setUp(self):
        self.apps = {
            "app1": {
                "services": {name: {"enabled": True} for name in FEATURES},
                "csp": {"whitelist": {"frame-src": [f"*.{PRIMARY}"]}},
            },
            "svc-net-tor": {"services": {"tor": {"node": NODE}}},
        }
        self.domains = {
            app: [f"{label}.{PRIMARY}", f"{label}.{NODE}"]
            for app, label in PROVIDERS.items()
        }

    def _header(self, vhost):
        return FilterModule().build_csp_header(
            self.apps,
            "app1",
            self.domains,
            "https",
            domain_primary=PRIMARY,
            vhost_domain=vhost,
        )

    def test_a_clearnet_vhost_names_only_clearnet_hosts(self):
        hosts = _hosts(self._header(f"app1.{PRIMARY}"))
        self.assertIn(f"cdn.{PRIMARY}", hosts)
        self.assertEqual({h for h in hosts if network_of(h) != CLEARNET}, set())

    def test_an_onion_vhost_names_only_onion_hosts_and_the_issuer(self):
        hosts = _hosts(self._header(f"app1.{NODE}"))
        self.assertIn(f"cdn.{NODE}", hosts)
        self.assertIn(ISSUER, hosts)
        self.assertEqual(
            {h for h in hosts if network_of(h) != TOR and h != ISSUER}, set()
        )


if __name__ == "__main__":
    unittest.main()
