from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

SPECS = PROJECT_ROOT / "roles" / "web-svc-logout" / "files" / "playwright"
KEYCLOAK_JS_SPECS = (
    "test-logout-choices.js",
    "test-logout-device.js",
)
TEST_IMPORT = re.compile(r"const \{[^}]*\btest\b[^}]*\} = require\(\"([^\"]+)\"\);")


class TestOnionBrowser(unittest.TestCase):
    def test_every_keycloak_js_spec_runs_in_the_onion_browser(self) -> None:
        for name in KEYCLOAK_JS_SPECS:
            with self.subTest(spec=name):
                sources = TEST_IMPORT.findall(read_text(str(SPECS / name)))
                self.assertEqual(
                    sources,
                    ["./onion-test"],
                    "keycloak-js on the onion dashboard needs the Web Crypto API, "
                    "which a plaintext .onion offers only as a secure context; the "
                    "shared onion-test fixture runs these specs in Firefox, the "
                    "engine of Tor Browser, with dom.securecontext.allowlist_onions",
                )


if __name__ == "__main__":
    unittest.main()
