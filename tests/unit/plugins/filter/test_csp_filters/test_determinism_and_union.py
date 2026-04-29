import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspDeterminismAndUnion(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "services": {"matomo": {"enabled": False}},
                "server": {
                    "csp": {
                        "whitelist": {"connect-src": []},
                        "flags": {
                            "script-src": {"unsafe-inline": False, "unsafe-eval": True}
                        },
                        "hashes": {},
                    }
                },
            }
        }
        self.domains = {"web-svc-cdn": ["cdn.example.org"]}

    def _get_directive_tokens(self, header: str, directive: str):
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(directive + " "):
                remainder = part[len(directive) :].strip()
                return [tok for tok in remainder.split(" ") if tok]
        return []

    def test_connect_src_tokens_sorted_and_self_first(self):
        apps = copy.deepcopy(self.apps)
        apps["app1"]["server"]["csp"]["whitelist"]["connect-src"] = [
            "https://zzz.example.com",
            "https://aaa.example.com",
            "https://mmm.example.com",
        ]
        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        tokens = self._get_directive_tokens(header, "connect-src")
        self.assertGreater(len(tokens), 0)
        self.assertEqual(tokens[0], "'self'")
        self.assertEqual(tokens[1:], sorted(tokens[1:]))

    def test_connect_src_header_deterministic_for_unsorted_whitelist(self):
        apps1 = copy.deepcopy(self.apps)
        apps2 = copy.deepcopy(self.apps)

        apps1["app1"]["server"]["csp"]["whitelist"]["connect-src"] = [
            "https://c.example.com",
            "https://b.example.com",
            "https://a.example.com",
        ]
        apps2["app1"]["server"]["csp"]["whitelist"]["connect-src"] = [
            "https://a.example.com",
            "https://c.example.com",
            "https://b.example.com",
        ]

        h1 = self.filter.build_csp_header(apps1, "app1", self.domains, "https")
        h2 = self.filter.build_csp_header(apps2, "app1", self.domains, "https")
        self.assertEqual(h1, h2)

    def test_style_family_union_flows_into_base_only_no_mirror_back(self):
        apps = copy.deepcopy(self.apps)
        apps["app1"]["server"]["csp"].setdefault("whitelist", {})
        apps["app1"]["server"]["csp"]["whitelist"]["style-src-elem"] = [
            "https://elem-only.example.com"
        ]
        apps["app1"]["server"]["csp"]["whitelist"]["style-src-attr"] = [
            "https://attr-only.example.com"
        ]

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        base = self._get_directive_tokens(header, "style-src")
        elem = self._get_directive_tokens(header, "style-src-elem")
        attr = self._get_directive_tokens(header, "style-src-attr")

        self.assertIn("https://elem-only.example.com", base)
        self.assertIn("https://attr-only.example.com", base)
        self.assertIn("https://elem-only.example.com", elem)
        self.assertIn("https://attr-only.example.com", attr)

    def test_no_unintended_mirroring_back_to_elem_attr(self):
        apps = copy.deepcopy(self.apps)
        apps["app1"]["server"]["csp"].setdefault("whitelist", {})
        apps["app1"]["server"]["csp"]["whitelist"]["style-src"] = [
            "https://base-only.example.com"
        ]

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        base = self._get_directive_tokens(header, "style-src")
        elem = self._get_directive_tokens(header, "style-src-elem")
        attr = self._get_directive_tokens(header, "style-src-attr")

        self.assertIn("https://base-only.example.com", base)
        self.assertNotIn("https://base-only.example.com", elem)
        self.assertNotIn("https://base-only.example.com", attr)


if __name__ == "__main__":
    unittest.main()
