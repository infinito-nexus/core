import unittest
import unittest.mock

from ansible.errors import AnsibleError

import plugins.lookup.backchannel_receiver as receiver_mod

APP = "web-app-openwebui"
LANDING = "https://chat.example.test/"
RECEIVER = "/oauth/backchannel-logout"
ANSWERS = {
    ("landing_url", (APP,)): LANDING,
    ("config", (APP, receiver_mod.RECEIVER_PATH)): RECEIVER,
}


def _get(name, **_kwargs):
    return unittest.mock.MagicMock(
        run=lambda terms, **_kw: [ANSWERS[(name, tuple(terms))]]
    )


class TestBackchannelReceiver(unittest.TestCase):
    def _run(self, terms):
        lookup = receiver_mod.LookupModule()
        lookup._loader = unittest.mock.MagicMock()
        with unittest.mock.patch.object(receiver_mod, "lookup_loader") as loader:
            loader.get.side_effect = _get
            return lookup.run(terms, variables={})

    def test_the_receiver_path_sits_under_the_landing_url(self):
        self.assertEqual(
            self._run([APP]),
            [f"https://chat.example.test{RECEIVER}"],
            "a sibling that hands its network over answers a POST with a 302, "
            "which a client follows as a GET, so the token must go where "
            "landing_url lands",
        )

    def test_anything_but_one_application_id_fails_loudly(self):
        with self.assertRaises(AnsibleError):
            self._run([])
        with self.assertRaises(AnsibleError):
            self._run([APP, APP])


if __name__ == "__main__":
    unittest.main()
