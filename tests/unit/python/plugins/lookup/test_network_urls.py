import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.network_urls as network_urls_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
SIBLINGS = {f"vault.{PRIMARY}": [f"vault.{PRIMARY}", f"vault.{ONION}"]}
BASES = {
    f"vault.{PRIMARY}": f"https://vault.{PRIMARY}/",
    f"vault.{ONION}": f"http://vault.{ONION}/",
}


def _loader():
    def _get(name, **_k):
        if name == "network_siblings":
            return mock.MagicMock(
                run=lambda terms, **_kw: [SIBLINGS.get(terms[0], [terms[0]])]
            )
        return mock.MagicMock(run=lambda terms, **_kw: [BASES[terms[0]]])

    loader = mock.MagicMock()
    loader.get.side_effect = _get
    return mock.patch.object(network_urls_mod, "lookup_loader", loader)


class TestNetworkUrls(unittest.TestCase):
    def _run(self, *terms):
        lookup = network_urls_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader():
            return lookup.run(list(terms), variables={})[0]

    def test_every_sibling_gets_the_url_with_its_scheme_canonical_first(self):
        self.assertEqual(
            self._run(f"https://vault.{PRIMARY}/v1/auth/oidc/callback?x=1"),
            [
                f"https://vault.{PRIMARY}/v1/auth/oidc/callback?x=1",
                f"http://vault.{ONION}/v1/auth/oidc/callback?x=1",
            ],
        )

    def test_a_host_without_siblings_comes_back_alone(self):
        url = "https://example.org/callback"
        self.assertEqual(self._run(url), [url])

    def test_more_than_one_term_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run("https://a/", "https://b/")


if __name__ == "__main__":
    unittest.main()
