import unittest

from plugins.filter.csp_filters import FilterModule


class TestCspWhitelistAndFlags(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "docker": {"services": {"matomo": {"enabled": True}}},
                "csp": {
                    "whitelist": {
                        "script-src-elem": ["https://cdn.example.com"],
                        "connect-src": "https://api.example.com",
                    },
                    "flags": {
                        "script-src": {"unsafe-eval": True, "unsafe-inline": False},
                        "style-src": {"unsafe-inline": True},
                    },
                    "hashes": {
                        "script-src": ["console.log('hello');"],
                        "style-src": ["body { background: #fff; }"],
                    },
                },
            },
            "app2": {},
        }

    def test_get_csp_whitelist_list(self):
        result = self.filter.get_csp_whitelist(self.apps, "app1", "script-src-elem")
        self.assertEqual(result, ["https://cdn.example.com"])

    def test_get_csp_whitelist_string(self):
        result = self.filter.get_csp_whitelist(self.apps, "app1", "connect-src")
        self.assertEqual(result, ["https://api.example.com"])

    def test_get_csp_whitelist_none(self):
        result = self.filter.get_csp_whitelist(self.apps, "app1", "font-src")
        self.assertEqual(result, [])

    def test_get_csp_flags_eval(self):
        result = self.filter.get_csp_flags(self.apps, "app1", "script-src")
        self.assertIn("'unsafe-eval'", result)
        self.assertNotIn("'unsafe-inline'", result)

    def test_get_csp_flags_inline(self):
        result = self.filter.get_csp_flags(self.apps, "app1", "style-src")
        self.assertIn("'unsafe-inline'", result)
        self.assertNotIn("'unsafe-eval'", result)

    def test_get_csp_flags_none(self):
        result = self.filter.get_csp_flags(self.apps, "app1", "connect-src")
        self.assertEqual(result, [])

    def test_flags_default_unsafe_inline_for_styles(self):
        self.assertIn(
            "'unsafe-inline'", self.filter.get_csp_flags(self.apps, "app2", "style-src")
        )
        self.assertIn(
            "'unsafe-inline'",
            self.filter.get_csp_flags(self.apps, "app2", "style-src-elem"),
        )
        self.assertNotIn(
            "'unsafe-inline'",
            self.filter.get_csp_flags(self.apps, "app2", "script-src"),
        )


if __name__ == "__main__":
    unittest.main()
