import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.network_redirects as network_redirects_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
SIBLINGS = {
    f"css.{PRIMARY}": [f"css.{PRIMARY}", f"css.{ONION}"],
    f"cdn.{PRIMARY}": [f"cdn.{PRIMARY}", f"cdn.{ONION}"],
    f"apex.{PRIMARY}": [f"apex.{PRIMARY}", f"apex.{ONION}"],
    ONION: [],
}


def _loader():
    siblings = mock.MagicMock(
        run=lambda terms, **_kw: [SIBLINGS.get(terms[0], [terms[0]])]
    )
    loader = mock.MagicMock()
    loader.get.return_value = siblings
    return mock.patch.object(network_redirects_mod, "lookup_loader", loader)


class TestNetworkRedirects(unittest.TestCase):
    def _run(self, *terms):
        lookup = network_redirects_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader():
            return lookup.run(list(terms), variables={})[0]

    def test_every_sibling_of_a_source_gets_the_mapping(self):
        target = f"cdn.{PRIMARY}"
        self.assertEqual(
            self._run([{"source": f"css.{PRIMARY}", "target": target}]),
            [
                {"source": f"css.{PRIMARY}", "target": target},
                {"source": f"css.{ONION}", "target": target},
            ],
        )

    def test_a_sibling_whose_network_the_target_does_not_reach_is_dropped(self):
        target = f"dashboard.{PRIMARY}"
        self.assertEqual(
            self._run([{"source": f"apex.{PRIMARY}", "target": target}]),
            [{"source": f"apex.{PRIMARY}", "target": target}],
            "an onion sibling redirecting to a clearnet-only target would send "
            "a Tor visitor off the onion",
        )

    def test_a_source_without_siblings_is_kept(self):
        mappings = [
            {"source": PRIMARY, "target": f"home.{PRIMARY}"},
            {"source": ONION, "target": f"home.{PRIMARY}"},
        ]
        self.assertEqual(self._run(mappings), mappings)

    def test_the_first_mapping_of_a_source_wins(self):
        mappings = [
            {"source": f"css.{PRIMARY}", "target": f"cdn.{PRIMARY}"},
            {"source": f"css.{ONION}", "target": f"other.{PRIMARY}"},
        ]
        self.assertEqual(
            [m["target"] for m in self._run(mappings)],
            [f"cdn.{PRIMARY}", f"cdn.{PRIMARY}"],
        )

    def test_a_mapping_without_source_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run([{"target": f"cdn.{PRIMARY}"}])


if __name__ == "__main__":
    unittest.main()
