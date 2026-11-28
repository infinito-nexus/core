"""The groups oidc.js hands the dashboard's lock chips, run in Node."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from .test_oidc_logout_everywhere import TEMPLATE, _render

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");

    async function settle() {
      for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
    }

    async function mount({ authenticated, tokenParsed }) {
      const events = [];
      const timers = [];
      const listeners = {};
      const kc = {
        authenticated, token: "secret-token", tokenParsed, logins: [],
        init: async (options) => { kc.initOptions = options; return authenticated; },
        updateToken: async () => true,
        logout: () => Promise.resolve(),
        login(options) { this.logins.push(options); return Promise.resolve(); },
      };
      globalThis.__fakeKeycloak = () => kc;
      global.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };
      global.history = { replaceState() {} };
      global.window = { location: { hash: "", pathname: "/", search: "" }, addEventListener() {} };
      global.document = {
        readyState: "complete",
        documentElement: { lang: "en" },
        querySelectorAll: () => [],
        querySelector: () => null,
        dispatchEvent: (event) => events.push(event),
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      };
      global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
      global.setTimeout = (fn) => timers.push(fn);
      (0, eval)(script);
      await settle();
      return { kc, events, timers, listeners };
    }

    (async () => {
      {
        const page = await mount({
          authenticated: true,
          tokenParsed: { exp: 4102444800, groups: ["/roles/web-app-wiki/administrator", 7, "offline_access"], email: "a@b.c" },
        });
        assert.strictEqual(page.events.length, 1, "init shares the groups once");
        assert.strictEqual(page.events[0].type, "dashboard:identity");
        assert.deepStrictEqual(page.events[0].detail, { groups: ["/roles/web-app-wiki/administrator", "offline_access"] },
          "only the string groups, never the token or another claim");
        page.kc.tokenParsed = { exp: 4102444800, groups: ["/roles/web-app-wiki/administrator", "/roles/web-app-blog/editor"] };
        await page.timers[0]();
        await settle();
        assert.strictEqual(page.events.length, 2, "a token refresh shares the groups again");
        assert.deepStrictEqual(page.events[1].detail.groups, ["/roles/web-app-wiki/administrator", "/roles/web-app-blog/editor"]);
        page.kc.updateToken = async () => { throw new Error("session expired"); };
        await page.timers[1]();
        await settle();
        assert.deepStrictEqual(page.events.at(-1).detail, { groups: null }, "a failed refresh forgets the groups");
        page.kc.onAuthLogout();
        assert.deepStrictEqual(page.events.at(-1).detail, { groups: null }, "a logout forgets the groups");
      }
      {
        const page = await mount({ authenticated: true, tokenParsed: { exp: 4102444800 } });
        assert.deepStrictEqual(page.events[0].detail, { groups: [] }, "a session without the claim holds no group");
      }
      {
        const page = await mount({ authenticated: false, tokenParsed: null });
        assert.deepStrictEqual(page.events[0].detail, { groups: null }, "an anonymous visitor is null");
        assert.strictEqual(page.listeners["dashboard:login"].length, 1, "oidc.js listens for the lock's sign-in request");
        page.listeners["dashboard:login"][0]();
        assert.strictEqual(page.kc.logins.length, 1, "the sign-in request starts the PKCE login");
        assert.strictEqual(page.kc.initOptions.pkceMethod, "S256", "the adapter runs the login with PKCE");
      }
      console.log("OK");
    })().catch((error) => { console.error(error); process.exit(1); });
    """
)


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestIdentityEvent(unittest.TestCase):
    def test_the_dashboard_shares_only_the_groups_at_init_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "oidc.js"
            script.write_text(_render(TEMPLATE))
            driver = Path(tmp) / "driver.js"
            driver.write_text(DRIVER)
            proc = subprocess.run(
                ["node", str(driver), str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
