from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SPEC = (
    PROJECT_ROOT
    / "roles"
    / "web-app-matomo"
    / "files"
    / "playwright"
    / "tracking.spec.js"
)
MATOMO_HOST = "matomo." + "a" * 56 + ".onion"
TARGET_HOST = "jenkins." + "a" * 56 + ".onion"
IDP_URL = "https://auth.example.test/realms/example"
TRACKER_HTML = (
    "<html><head><script>var _paq = window._paq = window._paq || [];"
    f'(function() {{ var u="http://{MATOMO_HOST}/";'
    '_paq.push(["setTrackerUrl", u+"matomo.php"]);'
    '_paq.push(["setSiteId", "3"]); })();</script></head><body></body></html>'
)

PLAYWRIGHT_STUB = textwrap.dedent(
    """
    const registered = [];
    function test(title, fn) {
      registered.push({ title, fn });
    }
    test.use = () => {};
    test.beforeEach = () => {};
    test.skip = (condition, reason) => {
      if (condition) {
        const error = new Error(reason);
        error.skipped = true;
        throw error;
      }
    };
    function expect(actual, message) {
      const check = (ok, what) => {
        if (!ok) {
          throw new Error(`${message || ""} (${what})`);
        }
      };
      return {
        toBe: (value) => check(actual === value, `expected ${value}, got ${actual}`),
        toBeLessThan: (value) => check(actual < value, `expected < ${value}, got ${actual}`),
        toBeGreaterThan: (value) => check(actual > value, `expected > ${value}, got ${actual}`),
        toBeTruthy: () => check(Boolean(actual), "expected truthy"),
        toContain: (value) => check(String(actual).includes(value), `expected to contain ${value}`),
        toEqual: (value) => check(JSON.stringify(actual) === JSON.stringify(value), "expected equal"),
      };
    }
    module.exports = { test, expect, registered };
    """
)

SHARED_STUB = textwrap.dedent(
    """
    const scenario = JSON.parse(process.env.SCENARIO);
    module.exports = {
      appBaseUrl: `http://${scenario.matomo_host}`,
      oidcIssuerUrl: scenario.idp_url,
      matomoApiToken: "",
      matomoTrackingScope: "",
      matomoCanonicalDomain: scenario.matomo_host,
      matomoTargetRoles: [scenario.target],
      hostOf: (value) => value,
      siteNeedleFor: (value) => value,
      setupMatomoPage: async () => {},
      loginAsAdmin: async () => {},
    };
    """
)

PERSONAS_STUB = textwrap.dedent(
    """
    module.exports = {
      gotoOnion: async (page, url) => page.goto(url),
      assertInjectedAssetLoadsWithoutCspBlock: async () => {
        process.stdout.write("ASSERTED\\n");
      },
    };
    """
)

TIMEOUTS_STUB = "module.exports = { resolveTimeout: (ms) => ms };\n"

DRIVER = textwrap.dedent(
    """
    const { registered } = require("@playwright/test");
    require("./tracking.spec.js");
    const scenario = JSON.parse(process.env.SCENARIO);
    const entry = registered.find((t) => t.title.startsWith(`matomo tracker injected in ${scenario.target.id} `));
    let current = "about:blank";
    const page = {
      request: {
        get: async (url) => ({ status: () => scenario.status, text: async () => scenario.html, url: () => url }),
      },
      goto: async (url) => {
        current = scenario.landing || url;
      },
      url: () => current,
      waitForURL: async (predicate) => {
        if (!predicate(new URL(current))) {
          throw new Error("waitForURL timed out");
        }
      },
      content: async () => scenario.html,
    };
    entry.fn({ page }).then(
      () => process.stdout.write("RAN\\n"),
      (error) => process.stdout.write(error.skipped ? `SKIP:${error.message}\\n` : `ERROR:${error.message}\\n`),
    );
    """
)


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestTrackingSpecIdpLanding(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stub = self.root / "node_modules" / "@playwright" / "test"
        stub.mkdir(parents=True)
        (stub / "package.json").write_text(
            json.dumps({"name": "@playwright/test", "main": "index.js"})
        )
        (stub / "index.js").write_text(PLAYWRIGHT_STUB)
        (self.root / "_shared.js").write_text(SHARED_STUB)
        (self.root / "personas.js").write_text(PERSONAS_STUB)
        (self.root / "timeouts.js").write_text(TIMEOUTS_STUB)
        (self.root / "run.js").write_text(DRIVER)
        shutil.copy(SPEC, self.root / "tracking.spec.js")

    def _run(self, status: int, landing: str) -> str:
        """Args:
            status: HTTP status the target's anonymous GET answers with.
            landing: URL the browser ends on after navigating to the target.

        Returns:
            The driver's stdout: ASSERTED and RAN, SKIP:<reason> or ERROR:<message>.
        """
        scenario = {
            "matomo_host": MATOMO_HOST,
            "idp_url": IDP_URL,
            "status": status,
            "html": TRACKER_HTML,
            "landing": landing,
            "target": {
                "id": "web-app-jenkins",
                "canonical_domain": TARGET_HOST,
                "canonical_url": f"http://{TARGET_HOST}",
                "is_proxy_gated": False,
            },
        }
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={**os.environ, "SCENARIO": json.dumps(scenario)},
            cwd=self.root,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_an_auth_challenge_carrying_the_tracker_that_lands_on_the_idp_is_skipped(
        self,
    ) -> None:
        out = self._run(403, f"{IDP_URL}/protocol/openid-connect/auth")
        self.assertIn(
            "SKIP:web-app-jenkins: its anonymous surface auto-redirects to the IdP", out
        )
        self.assertNotIn("ASSERTED", out)

    def test_an_auth_challenge_landing_off_the_idp_is_a_routing_fault(self) -> None:
        out = self._run(401, "https://elsewhere.example.test/")
        self.assertIn("ERROR:", out)
        self.assertIn("routing fault", out)
        self.assertNotIn("ASSERTED", out)

    def test_a_rendered_surface_carrying_the_tracker_is_asserted(self) -> None:
        out = self._run(200, f"http://{TARGET_HOST}/")
        self.assertIn("ASSERTED", out)
        self.assertIn("RAN", out)


if __name__ == "__main__":
    unittest.main()
