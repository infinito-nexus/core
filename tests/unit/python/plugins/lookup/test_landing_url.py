import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.landing_url as landing_url_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
CANONICAL = f"social.{PRIMARY}"
SIBLING = f"social.{ONION}"


def _loader(*, aligned: str, handover: bool):
    bases = {
        ("web-app-friendica", "url.base"): aligned,
        (CANONICAL, "url.base"): f"https://{CANONICAL}/",
    }
    lookups = {
        "tls": lambda terms: bases[tuple(terms)],
        "network_handover": lambda terms: (
            handover and terms == ["web-app-friendica", SIBLING]
        ),
        "domain": lambda terms: CANONICAL,
    }

    def _get(name, **_kwargs):
        return mock.MagicMock(run=lambda terms, **_kw: [lookups[name](terms)])

    loader = mock.MagicMock()
    loader.get.side_effect = _get
    return mock.patch.object(landing_url_mod, "lookup_loader", loader)


class TestLandingUrl(unittest.TestCase):
    def _run(self, terms, **loader_kwargs):
        lookup = landing_url_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader(**loader_kwargs):
            return lookup.run(terms, variables={})[0]

    def test_a_handover_sibling_lands_on_the_canonical_url(self):
        self.assertEqual(
            self._run(
                ["web-app-friendica"], aligned=f"http://{SIBLING}/", handover=True
            ),
            f"https://{CANONICAL}/",
            "the onion sibling of a handover application only redirects, so a "
            "browser opening it ends up on the canonical domain",
        )

    def test_a_served_sibling_keeps_the_aligned_url(self):
        self.assertEqual(
            self._run(
                ["web-app-friendica"], aligned=f"http://{SIBLING}/", handover=False
            ),
            f"http://{SIBLING}/",
        )

    def test_the_canonical_network_keeps_the_canonical_url(self):
        self.assertEqual(
            self._run(
                ["web-app-friendica"], aligned=f"https://{CANONICAL}/", handover=True
            ),
            f"https://{CANONICAL}/",
        )

    def test_anything_but_one_application_id_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run([], aligned=f"https://{CANONICAL}/", handover=False)
        with self.assertRaises(AnsibleError):
            self._run(["a", "b"], aligned=f"https://{CANONICAL}/", handover=False)


if __name__ == "__main__":
    unittest.main()
