import unittest

from plugins.filter.csp_filters import FilterModule


class TestCspStyleSrcElemDefaultInline(unittest.TestCase):
    def setUp(self):
        self.filter = FilterModule()
        self.apps = {
            "app1": {
                "docker": {"services": {"matomo": {"enabled": True}}},
                "server": {"csp": {"whitelist": {}, "flags": {}, "hashes": {}}},
            }
        }
        self.domains = {
            "web-app-matomo": ["matomo.example.org"],
            "web-svc-cdn": ["cdn.example.org"],
        }

    def _get_directive_tokens(self, header: str, directive: str):
        for raw_part in header.split(";"):
            part = raw_part.strip()
            if not part:
                continue
            if part.startswith(directive + " "):
                remainder = part[len(directive) :].strip()
                return [tok for tok in remainder.split(" ") if tok]
        return []

    def test_style_src_elem_default_unsafe_inline(self):
        """
        style-src-elem should include 'unsafe-inline' by default (from get_csp_flags defaults).
        """
        header = self.filter.build_csp_header(self.apps, "app1", self.domains, "https")
        tokens = self._get_directive_tokens(header, "style-src-elem")
        self.assertIn("'unsafe-inline'", tokens)


if __name__ == "__main__":
    unittest.main()
