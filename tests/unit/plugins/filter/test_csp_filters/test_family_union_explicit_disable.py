import unittest
import copy
from plugins.filter.csp_filters import FilterModule


class TestCspFamilyUnionExplicitDisable(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "services": {"matomo": {"enabled": True}},
                "server": {
                    "csp": {
                        "whitelist": {},
                        "flags": {
                            "script-src": {"unsafe-inline": False, "unsafe-eval": True},
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

    def test_style_explicit_disable_inline_on_base_survives_union(self):
        """
        If style-src.unsafe-inline is explicitly set to False on the base,
        it must be removed from the merged base even if elem/attr include it by default.
        """
        apps = copy.deepcopy(self.apps)

        # Explicitly disable unsafe-inline for the base
        apps["app1"].setdefault("server", {}).setdefault("csp", {}).setdefault(
            "flags", {}
        )
        apps["app1"]["server"]["csp"]["flags"].setdefault("style-src", {})
        apps["app1"]["server"]["csp"]["flags"]["style-src"]["unsafe-inline"] = False

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")

        base_tokens = self._get_directive_tokens(header, "style-src")
        elem_tokens = self._get_directive_tokens(header, "style-src-elem")
        attr_tokens = self._get_directive_tokens(header, "style-src-attr")

        # Base must NOT have 'unsafe-inline'
        self.assertNotIn("'unsafe-inline'", base_tokens)

        # elem/attr may still have 'unsafe-inline' by default (granularity preserved)
        self.assertIn("'unsafe-inline'", elem_tokens)
        self.assertIn("'unsafe-inline'", attr_tokens)

    def test_script_explicit_disable_inline_on_base_survives_union(self):
        """
        If script-src.unsafe-inline is explicitly set to False (default anyway),
        ensure the base remains without 'unsafe-inline' even if elem/attr enable it.
        """
        apps = copy.deepcopy(self.apps)

        # Force elem/attr to allow unsafe-inline explicitly
        apps["app1"].setdefault("server", {}).setdefault("csp", {}).setdefault(
            "flags", {}
        )
        apps["app1"]["server"]["csp"]["flags"]["script-src-elem"] = {
            "unsafe-inline": True
        }
        apps["app1"]["server"]["csp"]["flags"]["script-src-attr"] = {
            "unsafe-inline": True
        }

        # Explicitly disable on base
        apps["app1"]["server"]["csp"]["flags"]["script-src"] = {
            "unsafe-inline": False,
            "unsafe-eval": True,
        }

        header = self.filter.build_csp_header(apps, "app1", self.domains, "https")

        base_tokens = self._get_directive_tokens(header, "script-src")
        elem_tokens = self._get_directive_tokens(header, "script-src-elem")
        attr_tokens = self._get_directive_tokens(header, "script-src-attr")

        # Base: no 'unsafe-inline'
        self.assertNotIn("'unsafe-inline'", base_tokens)
        # But elem/attr: yes
        self.assertIn("'unsafe-inline'", elem_tokens)
        self.assertIn("'unsafe-inline'", attr_tokens)

        # Also ensure 'unsafe-eval' remains present on the base
        self.assertIn("'unsafe-eval'", base_tokens)


if __name__ == "__main__":
    unittest.main()
