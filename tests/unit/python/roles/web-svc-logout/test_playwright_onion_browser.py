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
                    "Chromium never treats a plaintext .onion origin as a secure "
                    "context, so keycloak-js on the onion dashboard fails with "
                    "'Web Crypto API is not available'; the shared onion-test "
                    "fixture launches Firefox with dom.securecontext.allowlist_onions",
                )


if __name__ == "__main__":
    unittest.main()
