import unittest
from plugins.filter.csp_filters import FilterModule


class TestCspBuildBasic(unittest.TestCase):
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
                        "hashes": {"script-src": ["console.log('hello');"]},
                    }
                },
            },
            "app2": {},
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

    def test_build_csp_header_basic(self):
        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")

        self.assertIn("default-src 'self';", header)

        self.assertIn("script-src-elem 'self'", header)
        self.assertIn("https://matomo.example.org", header)
        self.assertIn("https://cdn.example.org", header)
        self.assertIn("https://cdn.example.com", header)

        script_tokens = self._get_directive_tokens(header, "script-src")
        self.assertGreater(len(script_tokens), 0)
        self.assertEqual(script_tokens[0], "'self'")
        self.assertIn("'unsafe-eval'", script_tokens)

        connect_tokens = self._get_directive_tokens(header, "connect-src")
        self.assertIn("'self'", connect_tokens)
        self.assertIn("https://matomo.example.org", connect_tokens)
        self.assertIn("https://cdn.example.org", connect_tokens)
        self.assertIn("https://api.example.com", connect_tokens)

        self.assertTrue(header.strip().endswith("img-src * data: blob:;"))

    def test_build_csp_header_without_matomo_or_flags(self):
        header = self.filter.build_csp_header(self.apps, "app2", self.domains, "https")
        self.assertIn("default-src 'self';", header)
        self.assertIn("https://cdn.example.org", header)
        self.assertNotIn("matomo.example.org", header)
        self.assertNotIn("www.google.com", header)
        self.assertTrue(header.strip().endswith("img-src * data: blob:;"))


if __name__ == "__main__":
    unittest.main()
