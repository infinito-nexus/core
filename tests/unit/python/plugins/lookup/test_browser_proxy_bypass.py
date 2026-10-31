import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.browser_proxy_bypass as bypass_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
DOMAINS = {
    "web-app-deployed": [f"app.{PRIMARY}", f"app.{ONION}"],
    "web-app-elsewhere": [f"other.{PRIMARY}"],
}


def _loader():
    loader = mock.MagicMock()
    loader.get.return_value = mock.MagicMock(run=lambda terms, **_kw: [DOMAINS])
    return mock.patch.object(bypass_mod, "lookup_loader", loader)


class TestBrowserProxyBypassLookup(unittest.TestCase):
    def _run(self, terms, **variables):
        lookup = bypass_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader():
            return lookup.run(terms, variables=variables)[0]

    def test_only_deployed_clearnet_hosts_and_the_issuer_go_direct(self):
        self.assertEqual(
            self._run(
                ["tor", f"auth.{PRIMARY}"],
                group_names=["svc-net-tor", "web-app-deployed"],
            ),
            sorted([f"app.{PRIMARY}", f"auth.{PRIMARY}"]),
        )

    def test_a_tor_only_node_bypasses_nothing(self):
        self.assertEqual(
            self._run(
                ["tor", f"auth.{PRIMARY}"],
                group_names=["svc-net-tor", "web-app-deployed"],
                NETWORK_MODE="tor",
            ),
            [],
        )

    def test_a_mode_the_node_cannot_serve_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run(["tor"], group_names=["web-app-deployed"], NETWORK_MODE="multi")


if __name__ == "__main__":
    unittest.main()
