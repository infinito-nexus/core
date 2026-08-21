"""Behaviour of the logout status panel injected into Keycloak's logout page.

``roles/web-app-keycloak/templates/javascript.js.j2`` renders a per-domain
overview from ``postMessage`` reports sent by web-svc-logout's conductor, which
Keycloak loads as its front-channel logout URL. The two halves live in separate
repositories (the conductor ships from ``universal-logout``), so nothing but
this test holds the message contract - ``source``/``type``/``host``/``ok`` and
the ``start``/``host``/``done`` sequence - in place.

Four properties are load-bearing beyond the happy path:

* Silence must not read as success. The panel paints a pessimistic state on the
  logout page itself, before any message arrives, so a conductor that never
  loads leaves a visible "could not check" rather than Keycloak's plain
  "you are logged out".
* The origin equality check is a security boundary. Any framed page can post to
  this listener, and only the logout service may drive the panel or release the
  unload guard.
* Every terminal state names an action. "You can close this page now" is the
  question the visitor actually has; a status line that only describes is not
  an answer.
* The guard must fail open, and the timeout must state an outcome. A conductor
  that dies mid-sweep never sends ``done``; releasing the guard silently would
  leave a spinner that never resolves, which reads worse than an error.

The script is injected into ``<head>``, so it is exercised with
``readyState: "loading"`` at least once, and in the shape it is actually
served: collapsed by ``to_one_liner`` and inlined under a CSP hash.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from plugins.filter.text_filters import to_one_liner
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
PANEL = ROLE / "files" / "javascript" / "logout-panel.js"
ASSEMBLY = ROLE / "templates" / "logout-panel.js.j2"
CATALOGUE_FILE = ROLE / "files" / "logout_i18n.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN
FRAMED_ORIGIN_LOOKUP = "lookup('tls', 'web-svc-logout', 'url.base')"
ORIGIN = "https://logout.example.test"
DOMAINS = ("https://shop.example.test", "https://cloud.example.test")

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const ORIGIN = process.argv[3];
    const domains = process.argv.slice(4);
    const LOGOUT_PATH = "/realms/x/protocol/openid-connect/logout";
    const GRACE = 20000;
    const SWEEP = 60000;

    function element(tag) {
      const node = {
        tag, children: [], style: { cssText: "" }, attrs: {},
        id: "", title: "", href: "",
        setAttribute(k, v) { this.attrs[k] = v; },
        appendChild(child) { this.children.push(child); return child; },
      };
      let text = "";
      Object.defineProperty(node, "textContent", {
        get() { return text; },
        set(value) { text = value; node.children.length = 0; },
        enumerable: true,
      });
      return node;
    }

    function harness(opts) {
      opts = opts || {};
      const body = element("body");
      const on = {};
      const onDoc = {};
      const timers = {};
      let next = 0;

      global.document = {
        readyState: opts.readyState || "complete",
        createElement: element,
        querySelector: () => null,
        getElementById: () => opts.existing || null,
        documentElement: { lang: opts.lang === undefined ? "en" : opts.lang },
        body,
        addEventListener(type, fn) { (onDoc[type] = onDoc[type] || []).push(fn); },
      };
      Object.defineProperty(globalThis, "navigator", {
        value: { language: opts.navigator || "en" },
        configurable: true,
        writable: true,
      });
      global.window = {
        location: {
          pathname: opts.path === undefined ? LOGOUT_PATH : opts.path,
          hostname: opts.hostname || "auth.example.test",
        },
        addEventListener(type, fn) {
          on[type] = on[type] || [];
          if (!on[type].includes(fn)) { on[type].push(fn); }
        },
        removeEventListener(type, fn) {
          on[type] = (on[type] || []).filter((f) => f !== fn);
        },
      };
      global.setTimeout = (fn, ms) => { next += 1; timers[next] = { fn, ms }; return next; };
      global.clearTimeout = (id) => { if (id && timers[id]) { timers[id].cleared = true; } };

      eval(script);

      const live = (ms) =>
        Object.keys(timers).map((k) => timers[k]).filter((t) => t.ms === ms && !t.cleared);
      const api = {
        body,
        domReady() { (onDoc.DOMContentLoaded || []).forEach((fn) => fn()); },
        send(data, origin = ORIGIN) { (on.message || []).forEach((fn) => fn({ origin, data })); },
        post(payload) { api.send(Object.assign({ source: "universal-logout" }, payload)); },
        armed: () => (on.beforeunload || []).length,
        guard: () => on.beforeunload[0],
        scheduled: (ms) => live(ms).length > 0,
        fire(ms) {
          const hit = live(ms).pop();
          assert.ok(hit, `no live timer at ${ms}ms`);
          hit.fn();
        },
        panel: () => body.children[0],
        status: () => body.children[0].children[0].textContent,
        hint: () => body.children[0].children[1].textContent,
        counter: () => body.children[0].children[2].textContent,
        list: () => body.children[0].children[3],
        rowState: (i) => body.children[0].children[3].children[i].children[1].children[0].textContent,
        rowName: (i) => body.children[0].children[3].children[i].children[0],
        rowLink: (i) => body.children[0].children[3].children[i].children[1].children[1],
      };
      return api;
    }

    (function paintsPessimisticallyFromHead() {
      const h = harness({ readyState: "loading" });
      assert.strictEqual(h.body.children.length, 0, "nothing rendered before DOM ready");
      h.domReady();
      assert.match(h.status(), /Checking your other sessions/, "silence must not read as success");
      assert.match(h.hint(), /do not close this page/i, "the hint must name the action");
      assert.strictEqual(h.armed(), 1, "guard armed before any message");
      assert.ok(h.scheduled(GRACE), "grace timer armed on load");
      assert.strictEqual(h.panel().attrs["role"], "status");
      assert.strictEqual(h.panel().attrs["aria-live"], "polite");
    })();

    (function staysOffEveryOtherKeycloakPage() {
      const h = harness({ path: "/realms/x/account" });
      assert.strictEqual(h.body.children.length, 0, "no panel outside the logout page");
      assert.strictEqual(h.armed(), 0, "no guard outside the logout page");
    })();

    (function conductorNeverLoads() {
      const h = harness({});
      h.fire(GRACE);
      assert.match(h.status(), /Could not check your other sessions/);
      assert.match(h.hint(), /sign out of the remaining services yourself/);
      assert.strictEqual(h.armed(), 0, "guard released when the check gave up");
      assert.strictEqual(h.list().children[0].children[0].href, ORIGIN, "offers the logout page");
    })();

    (function happyPath() {
      const h = harness({});
      h.post({ type: "start", domains });

      assert.match(h.status(), /Signing you out/);
      assert.match(h.hint(), /keep this page open/i, "tells the visitor to wait");
      assert.match(h.hint(), /usually takes a few seconds/, "sets an expectation");
      assert.strictEqual(h.counter(), "0 of 2 services signed out");
      assert.strictEqual(h.rowName(0).textContent, "Shop", "service name, not a URL");
      assert.strictEqual(h.rowName(0).title, domains[0], "full host kept on hover");
      assert.match(h.rowState(0), /signing out/, "state carries text, not just a glyph");
      assert.ok(h.scheduled(SWEEP), "sweep timer armed on start");

      let prevented = false;
      h.guard()({ preventDefault: () => { prevented = true; } });
      assert.ok(prevented, "guard holds the page while the sweep runs");

      h.post({ type: "host", host: domains[0], ok: true });
      assert.match(h.rowState(0), /signed out/);
      assert.strictEqual(h.counter(), "1 of 2 services signed out");

      h.post({ type: "host", host: domains[1], ok: false });
      assert.match(h.rowState(1), /failed/);
      assert.strictEqual(
        h.rowLink(1).href, domains[1] + "/logout?manual=1",
        "a failure must offer a way out",
      );

      h.send(
        { source: "universal-logout", type: "host", host: "https://evil.test", ok: true },
        "https://evil.test",
      );
      assert.strictEqual(h.list().children.length, 2, "foreign origin ignored");

      h.post({ type: "done", total: 2, failed: 1 });
      assert.match(h.status(), /except 1 of 2/);
      assert.match(h.hint(), /sign out of the rest yourself/);
      assert.strictEqual(h.armed(), 0, "guard released when done");
      assert.ok(!h.scheduled(SWEEP), "sweep timer cancelled when done");

      h.send({ source: "universal-logout", type: "start", domains }, "https://evil.test");
      assert.strictEqual(h.armed(), 0, "foreign origin cannot re-arm the guard");
    })();

    (function cleanSweepSaysYouMayLeave() {
      const h = harness({});
      h.post({ type: "start", domains });
      h.post({ type: "host", host: domains[0], ok: true });
      h.post({ type: "host", host: domains[1], ok: true });
      h.post({ type: "done", total: 2, failed: 0 });
      assert.match(h.status(), /Signed out everywhere/);
      assert.match(h.hint(), /You can close this page now/, "answers the only question there is");
      assert.strictEqual(h.counter(), "2 of 2 services signed out");
      assert.strictEqual(h.armed(), 0);
    })();

    (function conductorDiesMidSweep() {
      const h = harness({});
      h.post({ type: "start", domains });
      h.post({ type: "host", host: domains[0], ok: true });
      assert.strictEqual(h.armed(), 1, "guard still armed while the sweep is incomplete");

      h.fire(SWEEP);
      assert.strictEqual(h.armed(), 0, "guard fails open when done never arrives");
      assert.match(h.status(), /Could not confirm every sign-out/, "a stall must state an outcome");
      assert.doesNotMatch(h.status(), /Signed out everywhere/, "and must not claim success");
      assert.match(h.rowState(1), /not confirmed/, "the pending row says so");
      assert.strictEqual(h.rowLink(1).href, domains[1] + "/logout?manual=1");
      assert.match(h.rowState(0), /signed out/, "a confirmed row is left alone");
    })();

    (function onionSessionsGetTheirOwnExpectation() {
      const h = harness({ hostname: "abcdefghij.onion" });
      h.post({ type: "start", domains });
      assert.match(h.hint(), /Over Tor this can take a while/);
    })();

    (function followsTheLanguageKeycloakChose() {
      const h = harness({ lang: "de" });
      h.post({ type: "start", domains });
      assert.match(h.status(), /Sie werden von Ihren Diensten abgemeldet/);
      h.post({ type: "done", total: 2, failed: 0 });
      assert.match(h.hint(), /Sie können diese Seite jetzt schließen/);
      assert.strictEqual(h.panel().attrs["dir"], "ltr");
    })();

    (function aRegionalTagFallsBackToItsBaseLanguage() {
      const h = harness({ lang: "pt-BR" });
      h.post({ type: "start", domains });
      assert.match(h.status(), /A terminar a sua sessão/);
    })();

    (function theBrowserDecidesWhenKeycloakSaysNothing() {
      const h = harness({ lang: "", navigator: "ja-JP" });
      h.post({ type: "start", domains });
      assert.match(h.status(), /ログアウトしています/);
    })();

    (function anUnknownLanguageFallsBackToEnglish() {
      const h = harness({ lang: "klingon", navigator: "klingon" });
      h.post({ type: "start", domains });
      assert.match(h.status(), /Signing you out of your services/);
    })();

    (function rightToLeftLanguagesFlipThePanel() {
      const h = harness({ lang: "ar" });
      h.post({ type: "start", domains });
      assert.strictEqual(h.panel().attrs["dir"], "rtl", "Arabic must render right-to-left");
      assert.match(h.status(), /جارٍ تسجيل خروجك/);
    })();

    (function countersAreFilledNotConcatenated() {
      const h = harness({ lang: "de" });
      h.post({ type: "start", domains });
      h.post({ type: "host", host: domains[0], ok: true });
      assert.strictEqual(h.counter(), "1 von 2 Diensten abgemeldet");
      h.post({ type: "done", total: 2, failed: 1 });
      assert.match(h.status(), /Abgemeldet, außer bei 1 von 2 Diensten/);
      assert.doesNotMatch(h.status(), /\\{failed\\}|\\{total\\}/, "no placeholder may survive");
    })();

    console.log("OK");
    """
)


def _collapsed_panel() -> str:
    """Render the template the way sys-front-inj-javascript serves it.

    :return: the one-lined script with both lookups resolved - the logout
        origin and the real translation catalogue
    """
    catalogue = json.dumps(load_yaml(CATALOGUE_FILE), ensure_ascii=False)
    prelude = (
        "window.__INFINITO_LOGOUT__ = {"
        f"origin: {json.dumps(ORIGIN)}, i18n: {catalogue}"
        "};"
    )
    return to_one_liner(prelude + "\n" + read_text(str(PANEL)))


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestLogoutStatusPanel(unittest.TestCase):
    def _collapsed(self) -> str:
        return _collapsed_panel()

    def test_the_panel_guides_the_visitor_through_every_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "panel.js"
            script.write_text(self._collapsed())
            driver = Path(tmp) / "driver.js"
            driver.write_text(DRIVER)

            proc = subprocess.run(
                ["node", str(driver), str(script), ORIGIN, *DOMAINS],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)


class TestPanelTrustsTheFramedOrigin(unittest.TestCase):
    def test_the_panel_trusts_exactly_the_origin_keycloak_is_told_to_frame(
        self,
    ) -> None:
        declaration = next(
            (
                line
                for line in read_text(str(VARS)).splitlines()
                if line.startswith("KEYCLOAK_FRONTCHANNEL_LOGOUT_URL:")
            ),
            "",
        )
        self.assertTrue(
            declaration, f"KEYCLOAK_FRONTCHANNEL_LOGOUT_URL missing from {VARS}"
        )
        self.assertIn(
            FRAMED_ORIGIN_LOOKUP,
            declaration,
            "the front-channel logout URL decides which origin ends up framed",
        )
        self.assertIn(
            FRAMED_ORIGIN_LOOKUP,
            read_text(str(ASSEMBLY)),
            "the panel discards messages from any other origin, so its constant and"
            " the framed URL must come from one expression or the panel goes silent",
        )


if __name__ == "__main__":
    unittest.main()
