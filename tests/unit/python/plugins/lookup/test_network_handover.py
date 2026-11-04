import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

import plugins.lookup.network_handover as network_handover_mod
from utils.domains.default_primary import default_domain_primary

PRIMARY = default_domain_primary()
ONION = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
CANONICAL = {
    "web-app-moodle": f"academy.{PRIMARY}",
    "web-app-nextcloud": f"cloud.{PRIMARY}",
}
HANDOVER = {"web-app-moodle": True, "web-app-nextcloud": False}


def _loader(handover=HANDOVER):
    def _get(name, **_k):
        if name == "config":
            return mock.MagicMock(run=lambda terms, **_kw: [handover[terms[0]]])
        return mock.MagicMock(run=lambda terms, **_kw: [CANONICAL[terms[0]]])

    loader = mock.MagicMock()
    loader.get.side_effect = _get
    return mock.patch.object(network_handover_mod, "lookup_loader", loader)


class TestNetworkHandover(unittest.TestCase):
    def _run(self, terms, handover=HANDOVER):
        lookup = network_handover_mod.LookupModule()
        lookup._loader = mock.MagicMock()
        with _loader(handover):
            return lookup.run(terms, variables={"domain": terms[-1]})[0]

    def test_the_onion_sibling_of_a_handover_app_hands_over(self):
        self.assertIs(self._run(["web-app-moodle", f"academy.{ONION}"]), True)

    def test_the_canonical_vhost_of_a_handover_app_serves(self):
        self.assertIs(self._run(["web-app-moodle", f"academy.{PRIMARY}"]), False)

    def test_an_app_without_handover_serves_every_sibling(self):
        self.assertIs(self._run(["web-app-nextcloud", f"cloud.{ONION}"]), False)

    def test_a_non_boolean_flag_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-moodle", f"academy.{ONION}"], {"web-app-moodle": "yes"})

    def test_both_terms_are_required(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-moodle"])


if __name__ == "__main__":
    unittest.main()
