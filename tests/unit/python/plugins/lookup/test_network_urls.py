import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.network_urls as network_urls_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
BASES = {
    f"vault.{PRIMARY}": f"https://vault.{PRIMARY}/",
    f"vault.{ONION}": f"http://vault.{ONION}/",
}
DOMAINS = {"web-app-openbao": [f"vault.{PRIMARY}", f"vault.{ONION}"]}
TOR_NODE = {"DOMAIN_PRIMARY": PRIMARY, "group_names": ["svc-net-tor"]}
CALLBACK = "/v1/auth/oidc/callback?x=1"
EVERY_NETWORK = [
    f"https://vault.{PRIMARY}{CALLBACK}",
    f"http://vault.{ONION}{CALLBACK}",
]


def _loader():
    lookups = {
        "domains": lambda terms: DOMAINS,
        "config": lambda terms: ONION,
        "tls": lambda terms: BASES[terms[0]],
    }

    def _get(name, **_k):
        return mock.MagicMock(run=lambda terms, **_kw: [lookups[name](terms)])

    loader = mock.MagicMock()
    loader.get.side_effect = _get
    return mock.patch.object(network_urls_mod, "lookup_loader", loader)


class TestNetworkUrls(unittest.TestCase):
    def _run(self, *terms):
        lookup = network_urls_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader():
            return lookup.run(list(terms), variables=TOR_NODE)[0]

    def test_the_canonical_sibling_gets_every_network_canonical_first(self):
        self.assertEqual(self._run(f"https://vault.{PRIMARY}{CALLBACK}"), EVERY_NETWORK)

    def test_a_non_canonical_sibling_gets_every_network_canonical_first(self):
        self.assertEqual(
            self._run(f"http://vault.{ONION}{CALLBACK}"),
            EVERY_NETWORK,
            "network_siblings answers [] for the onion sibling because its "
            "canonical twin renders the vhost; the URL list must still name "
            "every network, clearnet first",
        )

    def test_a_host_the_map_does_not_know_comes_back_alone(self):
        url = "https://example.org/callback"
        self.assertEqual(self._run(url), [url])

    def test_more_than_one_term_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run("https://a/", "https://b/")


if __name__ == "__main__":
    unittest.main()
