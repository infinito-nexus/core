import copy
import unittest

from plugins.filter.csp_filters import FilterModule
from utils.domains.default_primary import default_domain_primary

NODE = "ndck3kzcxbcem2oskbhytxwevvpzwn7j5dj6q36vbijyrnw3rjf2heqd.onion"
PRIMARY = default_domain_primary()
CLEARNET = "app1." + PRIMARY
ONION = "app1." + NODE


class TestCspVhostHashes(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {"csp": {"whitelist": {}, "flags": {}, "hashes": {}}},
            "svc-net-tor": {"services": {"tor": {"node": NODE}}},
        }
        self.domains = {
            "web-svc-cdn": ["cdn." + PRIMARY, "cdn." + NODE],
            "app1": [CLEARNET, ONION],
        }
        self.store = {
            CLEARNET: {"script-src-elem": ["track('" + CLEARNET + "');"]},
            ONION: {"script-src-elem": ["track('" + ONION + "');"]},
        }

    def _tokens(self, header, directive):
        for raw in header.split(";"):
            part = raw.strip()
            if part.startswith(directive + " "):
                return [t for t in part[len(directive) :].strip().split(" ") if t]
        return []

    def _header(self, vhost, store):
        return self.filter.build_csp_header(
            copy.deepcopy(self.apps),
            "app1",
            self.domains,
            "https",
            None,
            store,
            PRIMARY,
            vhost,
        )

    def test_each_sibling_carries_only_its_own_hashes(self):
        clearnet_hash = self.filter.get_csp_hash("track('" + CLEARNET + "');")
        onion_hash = self.filter.get_csp_hash("track('" + ONION + "');")

        clearnet = self._tokens(self._header(CLEARNET, self.store), "script-src-elem")
        onion = self._tokens(self._header(ONION, self.store), "script-src-elem")

        self.assertIn(clearnet_hash, clearnet)
        self.assertNotIn(onion_hash, clearnet)
        self.assertIn(onion_hash, onion)
        self.assertNotIn(clearnet_hash, onion)

    def test_sibling_without_snippets_carries_no_hash(self):
        store = {**self.store, ONION: {}}
        onion = self._tokens(self._header(ONION, store), "script-src-elem")
        self.assertFalse([t for t in onion if t.startswith("'sha256-")])

    def test_sibling_without_injection_pass_carries_no_hash(self):
        store = {CLEARNET: self.store[CLEARNET]}
        onion = self._tokens(self._header(ONION, store), "script-src-elem")
        self.assertFalse([t for t in onion if t.startswith("'sha256-")])

    def test_store_without_any_injection_pass_matches_no_store(self):
        self.assertEqual(self._header(CLEARNET, {}), self._header(CLEARNET, None))


if __name__ == "__main__":
    unittest.main()
