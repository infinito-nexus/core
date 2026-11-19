from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

LOGOUT_FLOW = (
    PROJECT_ROOT
    / "roles"
    / "web-svc-logout"
    / "files"
    / "playwright"
    / "logout-flow.js"
)

STUBS = {
    "node_modules/@playwright/test/package.json": json.dumps(
        {"name": "@playwright/test", "main": "index.js"}
    ),
    "node_modules/@playwright/test/index.js": """
        module.exports = {
          expect: (target, message) => ({
            toBeVisible: async () => {
              if (!(await target.isVisible())) throw new Error(message || "not visible");
            },
          }),
        };
    """,
    "personas/index.js": """
        const calls = [];
        module.exports = {
          calls,
          OIDC_LOGIN_READY_FLAG: "__oidcLoginReady",
          apiFetchOnion: async () => null,
          apiGetOnion: async () => null,
          clickOidcLoginLink: async (page) => {
            calls.push("click");
            if (!page.loginVisible) throw new Error("clicked a Login link the dashboard hides");
            page.signedIn = true;
            return null;
          },
          decodeDotenvJsonList: () => [],
          decodeDotenvQuotedValue: (value) => value,
          gotoOnion: async (page) => page.events.push("goto"),
          performKeycloakLoginForm: async () => calls.push("form"),
          requireDotenvValue: (value) => value || "set",
        };
    """,
    "personas/utils/network.js": "module.exports = { isTorUrl: () => false };",
    "timeouts.js": "module.exports = { isOnionTarget: () => false, resolveTimeout: (ms) => ms };",
}

RUNNER = """
    const { calls } = require("./personas");
    const { signInToDashboard } = require("./logout-flow");
    function fakePage(signedInBySso) {
      const page = { events: [], ready: false, signedIn: false };
      const visibleOnceReady = (wanted) => async () => page.ready && wanted();
      const account = { first: () => account, isVisible: visibleOnceReady(() => page.signedIn) };
      const login = { first: () => login, filter: () => login, isVisible: visibleOnceReady(() => !page.signedIn) };
      const header = { first: () => header, getByRole: () => account, locator: () => login };
      page.locator = () => header;
      page.waitForFunction = async (_fn, flag) => {
        page.events.push("wait:" + flag);
        page.ready = true;
        page.signedIn = signedInBySso;
      };
      Object.defineProperty(page, "loginVisible", { get: () => page.ready && !page.signedIn });
      return page;
    }
    (async () => {
      const page = fakePage(process.argv[2] === "sso");
      try {
        await signInToDashboard(page, "http://dashboard.example.onion/");
        process.stdout.write(JSON.stringify({ calls, events: page.events, signedIn: page.signedIn }));
      } catch (error) {
        process.stdout.write(JSON.stringify({ calls, events: page.events, error: error.message }));
      }
    })();
"""


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestSignInToDashboard(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(tempfile.mkdtemp(prefix="logout-flow-"))
        for relative, source in {**STUBS, "run.js": RUNNER}.items():
            target = self.workdir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w") as handle:
                handle.write(textwrap.dedent(source))
        shutil.copy(str(LOGOUT_FLOW), str(self.workdir / "logout-flow.js"))

    def tearDown(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _sign_in(self, mode: str) -> dict:
        proc = subprocess.run(
            ["node", "run.js", mode],
            capture_output=True,
            text=True,
            cwd=str(self.workdir),
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return json.loads(proc.stdout)

    def test_a_dashboard_the_shared_keycloak_session_signed_in_is_not_clicked(
        self,
    ) -> None:
        result = self._sign_in("sso")
        self.assertNotIn("error", result, result)
        self.assertEqual(
            result["calls"],
            [],
            "the second network's dashboard signs biber in through the single issuer's "
            "session, so its Login link is hidden and a click waits out its timeout",
        )

    def test_a_signed_out_dashboard_is_signed_in_through_its_login_link(self) -> None:
        result = self._sign_in("signed-out")
        self.assertNotIn("error", result, result)
        self.assertEqual(result["calls"], ["click"])
        self.assertTrue(result["signedIn"])

    def test_the_header_is_read_only_after_oidc_js_settled_it(self) -> None:
        result = self._sign_in("sso")
        self.assertEqual(result["events"], ["goto", "wait:__oidcLoginReady"])


if __name__ == "__main__":
    unittest.main()
