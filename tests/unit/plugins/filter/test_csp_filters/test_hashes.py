import unittest
import hashlib
import base64
from plugins.filter.csp_filters import FilterModule, AnsibleFilterError


class TestCspHashes(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "services": {"matomo": {"enabled": True}},
                "server": {
                    "csp": {
                        "whitelist": {},
                        "flags": {
                            "script-src": {"unsafe-eval": True, "unsafe-inline": False},
                            "style-src": {"unsafe-inline": True},
                        },
                        "hashes": {
                            "script-src": ["console.log('hello');"],
                            "style-src": ["body { background: #fff; }"],
                        },
                    }
                },
            }
        }
        self.domains = {
            "web-app-matomo": ["matomo.example.org"],
            "web-svc-cdn": ["cdn.example.org"],
        }

    def test_get_csp_hash_known_value(self):
        content = "alert(1);"
        digest = hashlib.sha256(content.encode("utf-8")).digest()
        b64 = base64.b64encode(digest).decode("utf-8")
        expected = f"'sha256-{b64}'"
        self.assertEqual(self.filter.get_csp_hash(content), expected)

    def test_get_csp_hash_error(self):
        with self.assertRaises(AnsibleFilterError):
            self.filter.get_csp_hash(None)

    def test_get_csp_inline_content_list(self):
        snippets = self.filter.get_csp_inline_content(self.apps, "app1", "script-src")
        self.assertEqual(snippets, ["console.log('hello');"])

    def test_get_csp_inline_content_string(self):
        self.apps["app1"]["server"]["csp"]["hashes"]["style-src"] = (
            "body { color: red; }"
        )
        snippets = self.filter.get_csp_inline_content(self.apps, "app1", "style-src")
        self.assertEqual(snippets, ["body { color: red; }"])

    def test_get_csp_inline_content_none(self):
        snippets = self.filter.get_csp_inline_content(self.apps, "app1", "font-src")
        self.assertEqual(snippets, [])

    def test_hashes_included_only_if_no_unsafe_inline(self):
        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")

        script_hash = self.filter.get_csp_hash("console.log('hello');")
        self.assertIn(script_hash, header)

        style_hash = self.filter.get_csp_hash("body { background: #fff; }")
        self.assertNotIn(style_hash, header)

    def test_style_src_hashes_suppressed_by_default(self):
        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")
        style_hash = self.filter.get_csp_hash("body { background: #fff; }")
        self.assertNotIn(style_hash, header)

    def test_style_src_disable_inline_enables_hashes(self):
        self.apps["app1"]["server"]["csp"]["flags"].setdefault("style-src", {})
        self.apps["app1"]["server"]["csp"]["flags"]["style-src"]["unsafe-inline"] = (
            False
        )
        self.apps["app1"]["server"]["csp"]["hashes"]["style-src"] = (
            "body{background:#fff}"
        )

        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")
        self.assertIn(self.filter.get_csp_hash("body{background:#fff}"), header)

    def test_script_src_hash_behavior_depends_on_unsafe_inline(self):
        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")
        script_hash = self.filter.get_csp_hash("console.log('hello');")
        self.assertIn(script_hash, header)

        self.apps["app1"]["server"]["csp"]["flags"]["script-src"]["unsafe-inline"] = (
            True
        )
        header_inline = self.filter.build_csp_header(
            self.apps, "app1", self.domains, "https"
        )
        self.assertNotIn(script_hash, header_inline)


if __name__ == "__main__":
    unittest.main()
