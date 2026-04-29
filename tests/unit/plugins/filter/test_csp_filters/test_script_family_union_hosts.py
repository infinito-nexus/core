import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspScriptFamilyUnionHosts(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "services": {"matomo": {"enabled": True}},
                "server": {
                    "csp": {
                        "whitelist": {
                            "script-src-elem": ["https://cdn.example.com"],
                            "connect-src": "https://api.example.com",
                        },
                        "flags": {
                            "script-src": {"unsafe-eval": True, "unsafe-inline": False},
                            "style-src": {"unsafe-inline": True},
                        },
                        "hashes": {},
                    }
                },
            }
        }
        self.domains = {
            "web-app-matomo": ["matomo.example.org"],
            "web-svc-cdn": ["cdn.example.org"],
        }

    def _get_directive_tokens(self, header: str, directive: str):
        for part in header.split(";"):
            part = part.strip()
            if not part:
                continue
            if part.startswith(directive + " "):
                remainder = part[len(directive) :].strip()
                return [tok for tok in remainder.split(" ") if tok]
        return []

    def test_script_family_union_includes_elem_attr_hosts_in_base(self):
        """
        Hosts present only under script-src-elem/attr must appear in script-src (base).
        """
        apps = copy.deepcopy(self.apps)
        apps["app1"]["server"]["csp"].setdefault("whitelist", {})
        apps["app1"]["server"]["csp"]["whitelist"]["script-src-elem"] = [
            "https://elem-scripts.example.com"
        ]
        apps["app1"]["server"]["csp"]["whitelist"]["script-src-attr"] = [
            "https://attr-scripts.example.com"
        ]

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")

        base_tokens = self._get_directive_tokens(header, "script-src")
        self.assertIn("https://elem-scripts.example.com", base_tokens)
        self.assertIn("https://attr-scripts.example.com", base_tokens)


if __name__ == "__main__":
    unittest.main()
