import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspHashesFinalTokenGuard(unittest.TestCase):
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
                            # style-src flags may be removed in tests to rely on defaults
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

    def _get_directive_tokens(self, header: str, directive: str):
        for part in header.split(";"):
            part = part.strip()
            if not part:
                continue
            if part.startswith(directive + " "):
                remainder = part[len(directive) :].strip()
                return [tok for tok in remainder.split(" ") if tok]
        return []

    def test_hashes_guard_checks_final_tokens_not_only_flags(self):
        """
        Ensure the 'no-hash-when-unsafe-inline' rule is driven by FINAL tokens,
        not just raw flags: simulate default-provided 'unsafe-inline' (style-src)
        without explicitly setting it in flags and verify hashes are still suppressed.
        """
        apps = copy.deepcopy(self.apps)

        # Remove explicit style-src flags entirely to rely solely on defaults
        apps["app1"]["server"]["csp"]["flags"].pop("style-src", None)

        # Provide a style-src hash
        apps["app1"]["server"]["csp"]["hashes"]["style-src"] = "body { color: blue; }"
        style_hash = self.filter.get_csp_hash("body { color: blue; }")

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")

        # Because defaults include 'unsafe-inline' for style-src, the hash MUST NOT appear
        self.assertNotIn(style_hash, header)

        # And 'unsafe-inline' must appear in final tokens
        tokens = self._get_directive_tokens(header, "style-src")
        self.assertIn("'unsafe-inline'", tokens)

    def test_hash_inclusion_uses_final_base_tokens_after_union(self):
        """
        Ensure hash inclusion for style-src is evaluated after family union & explicit-disable logic.
        If base ends up WITHOUT 'unsafe-inline' after union, hashes must be present.
        """
        apps = copy.deepcopy(self.apps)

        # Explicitly disable 'unsafe-inline' on base 'style-src' so hashes can be included
        apps["app1"].setdefault("server", {}).setdefault("csp", {}).setdefault(
            "flags", {}
        )
        apps["app1"]["server"]["csp"]["flags"].setdefault("style-src", {})
        apps["app1"]["server"]["csp"]["flags"]["style-src"]["unsafe-inline"] = False

        # Provide a style-src hash
        content = "body { background: #abc; }"
        apps["app1"]["server"]["csp"].setdefault("hashes", {})["style-src"] = content
        expected_hash = self.filter.get_csp_hash(content)

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")
        base_tokens = self._get_directive_tokens(header, "style-src")

        self.assertNotIn("'unsafe-inline'", base_tokens)  # confirm no unsafe-inline
        self.assertIn(expected_hash, header)  # hash must be present


if __name__ == "__main__":
    unittest.main()
