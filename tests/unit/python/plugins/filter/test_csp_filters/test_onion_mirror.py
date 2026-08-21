import copy
import unittest

from plugins.filter.csp_filters import FilterModule

NODE = "ndck3kzcxbcem2oskbhytxwevvpzwn7j5dj6q36vbijyrnw3rjf2heqd.onion"
PRIMARY = "infinito.example"


class TestCspOnionMirror(unittest.TestCase):
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

    def _tokens(self, header, directive):
        for raw in header.split(";"):
            part = raw.strip()
            if part.startswith(directive + " "):
                return [t for t in part[len(directive) :].strip().split(" ") if t]
        return []

    def _header(self, app_domains):
        domains = {"web-svc-cdn": ["cdn." + PRIMARY], **app_domains}
        return self.filter.build_csp_header(
            copy.deepcopy(self.apps),
            "app1",
            domains,
            "http",
            domain_primary=PRIMARY,
        )

    def test_primary_keeps_clearnet_and_adds_onion(self):
        frame = self._tokens(
            self._header({"app1": ["app1." + NODE, "app1." + PRIMARY]}), "frame-src"
        )
        self.assertIn("*." + PRIMARY, frame)
        self.assertIn("*." + NODE, frame)

    def test_exclusive_replaces_clearnet_with_onion(self):
        frame = self._tokens(self._header({"app1": ["app1." + NODE]}), "frame-src")
        self.assertIn("*." + NODE, frame)
        self.assertNotIn("*." + PRIMARY, frame)

    def test_non_tor_app_unchanged(self):
        frame = self._tokens(self._header({"app1": ["app1." + PRIMARY]}), "frame-src")
        self.assertIn("*." + PRIMARY, frame)
        self.assertFalse(any(".onion" in t for t in frame))

    def test_no_mirror_without_node(self):
        apps = copy.deepcopy(self.apps)
        del apps["svc-net-tor"]
        domains = {"web-svc-cdn": ["cdn." + PRIMARY], "app1": ["app1." + NODE]}
        header = self.filter.build_csp_header(
            apps, "app1", domains, "http", domain_primary=PRIMARY
        )
        self.assertFalse(any(".onion" in t for t in self._tokens(header, "frame-src")))


if __name__ == "__main__":
    unittest.main()
