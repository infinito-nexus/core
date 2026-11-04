import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.network_url as network_url_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
SIBLINGS = {f"file.{PRIMARY}": [f"file.{PRIMARY}", f"file.{ONION}"]}
BASES = {
    f"file.{PRIMARY}": f"https://file.{PRIMARY}/",
    f"file.{ONION}": f"http://file.{ONION}/",
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
    return mock.patch.object(network_url_mod, "lookup_loader", loader)


class TestNetworkUrl(unittest.TestCase):
    def _run(self, url, variables):
        lookup = network_url_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader():
            return lookup.run([url], variables=variables)[0]

    def test_an_onion_vhost_gets_the_onion_sibling_with_its_scheme(self):
        self.assertEqual(
            self._run(
                f"https://file.{PRIMARY}/assets/img/logo.png?v=1",
                {"domain": f"dashboard.{ONION}"},
            ),
            f"http://file.{ONION}/assets/img/logo.png?v=1",
        )

    def test_a_clearnet_vhost_keeps_the_url(self):
        url = f"https://file.{PRIMARY}/assets/img/logo.png"
        self.assertEqual(self._run(url, {"domain": f"dashboard.{PRIMARY}"}), url)

    def test_a_host_the_node_does_not_serve_stays_unchanged(self):
        url = "https://example.org/logo.png"
        self.assertEqual(self._run(url, {"domain": f"dashboard.{ONION}"}), url)

    def test_a_missing_vhost_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run(f"https://file.{PRIMARY}/logo.png", {})


if __name__ == "__main__":
    unittest.main()
