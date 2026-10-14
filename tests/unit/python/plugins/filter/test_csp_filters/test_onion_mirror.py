import copy
import unittest

from plugins.filter.csp_filters import FilterModule
from utils.domains.default_primary import default_domain_primary

NODE = "ndck3kzcxbcem2oskbhytxwevvpzwn7j5dj6q36vbijyrnw3rjf2heqd.onion"
PRIMARY = default_domain_primary()


class TestCspOnionMirror(unittest.TestCase):
    """Whitelist sources under DOMAIN_PRIMARY follow the vhost's network."""

    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "csp": {
                    "whitelist": {"frame-src": ["*." + PRIMARY]},
                    "flags": {},
                    "hashes": {},
                },
            },
            "svc-net-tor": {"services": {"tor": {"node": NODE}}},
        }
        self.domains = {
            "web-svc-cdn": ["cdn." + PRIMARY, "cdn." + NODE],
            "app1": ["app1." + PRIMARY, "app1." + NODE],
        }

    def _tokens(self, header, directive):
        for raw in header.split(";"):
            part = raw.strip()
            if part.startswith(directive + " "):
                return [t for t in part[len(directive) :].strip().split(" ") if t]
        return []

    def _header(self, vhost, domains=None, apps=None):
        return self.filter.build_csp_header(
            copy.deepcopy(apps or self.apps),
            "app1",
            domains or self.domains,
            "https",
            domain_primary=PRIMARY,
            vhost_domain=vhost,
        )

    def test_clearnet_vhost_keeps_clearnet_sources(self):
        header = self._header("app1." + PRIMARY)
        self.assertEqual(self._tokens(header, "frame-src"), ["'self'", "*." + PRIMARY])
        self.assertIn("https://cdn." + PRIMARY, self._tokens(header, "connect-src"))
        self.assertNotIn(".onion", header)

    def test_onion_vhost_moves_sources_to_the_node_in_plaintext(self):
        header = self._header("app1." + NODE)
        self.assertEqual(self._tokens(header, "frame-src"), ["'self'", "*." + NODE])
        connect = self._tokens(header, "connect-src")
        self.assertIn("http://cdn." + NODE, connect)
        self.assertNotIn("https://cdn." + PRIMARY, connect)

    def test_tor_only_app_without_vhost_follows_its_primary(self):
        domains = {"web-svc-cdn": ["cdn." + NODE], "app1": ["app1." + NODE]}
        frame = self._tokens(self._header(None, domains=domains), "frame-src")
        self.assertIn("*." + NODE, frame)
        self.assertNotIn("*." + PRIMARY, frame)

    def test_role_without_tor_on_a_tor_node_keeps_its_sources(self):
        domains = {
            "web-svc-cdn": ["cdn." + PRIMARY, "cdn." + NODE],
            "app1": ["app1." + PRIMARY],
        }
        header = self._header(None, domains=domains)
        self.assertEqual(self._tokens(header, "frame-src"), ["'self'", "*." + PRIMARY])
        self.assertIn("https://cdn." + PRIMARY, self._tokens(header, "connect-src"))
        self.assertNotIn(".onion", header)

    def test_no_translation_without_node(self):
        apps = copy.deepcopy(self.apps)
        del apps["svc-net-tor"]
        frame = self._tokens(self._header("app1." + NODE, apps=apps), "frame-src")
        self.assertEqual(frame, ["'self'", "*." + PRIMARY])


if __name__ == "__main__":
    unittest.main()
