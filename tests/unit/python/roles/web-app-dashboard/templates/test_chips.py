"""The dashboard's lock and health chips, rendered as deployed and run in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-dashboard"
TEMPLATE = "templates/javascript/chips.js.j2"
GATE = "/roles/web-app-gated/administrator"
CARDS = [
    {"id": "web-app-gated", "allowed_groups": [GATE]},
    {"id": "web-app-open"},
]

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const scenario = process.argv[3];

    async function settle() {
      for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
    }

    function mount({ api, reply }) {
      const listeners = {};
      const chips = {};
      const fetches = [];
      const intervals = [];
      const logins = [];
      global.window = {};
      const portui = { chips: { set: (id, list) => { chips[id] = list; } } };
      if (api) global.window.portui = portui;
      global.document = {
        documentElement: { lang: "en" },
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        dispatchEvent(event) { (listeners[event.type] || []).forEach((fn) => fn(event)); },
      };
      global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init ? init.detail : undefined; } };
      global.fetch = async (url) => {
        fetches.push(url);
        if (!reply) throw new Error("offline");
        return { ok: true, json: async () => reply };
      };
      global.setInterval = (_fn, ms) => intervals.push(ms);
      (0, eval)(script);
      document.addEventListener("dashboard:login", () => logins.push(true));
      const emit = (type, detail) => document.dispatchEvent(new CustomEvent(type, { detail }));
      return { portui, listeners, chips, fetches, intervals, logins, emit };
    }

    const states = (list) => list.map((chip) => `${chip.kind}:${chip.state}`);
    const now = new Date().toISOString();

    (async () => {
      if (scenario === "locks") {
        const page = mount({ api: true, reply: null });
        assert.deepStrictEqual(page.chips["web-app-gated"], [], "no lock before the identity is known");
        page.emit("dashboard:identity", { groups: null });
        assert.deepStrictEqual(states(page.chips["web-app-gated"]), ["lock:signin"]);
        assert.deepStrictEqual(page.chips["web-app-open"], [], "an ungated card never shows a lock");
        page.emit("dashboard:identity", { groups: [GATE_PATH] });
        assert.deepStrictEqual(page.chips["web-app-gated"], [], "a member of the gate group opens the card");
        page.emit("dashboard:identity", { groups: ["/roles/web-app-other/administrator"] });
        const [lock] = page.chips["web-app-gated"];
        assert.strictEqual(lock.state, "request");
        assert.strictEqual(lock.href, "https://access.example.test/?application=web-app-gated");
        assert.strictEqual(lock.newTab, true);
        assert.deepStrictEqual(page.fetches, [], "no status poll while the badges are switched off");
        let prevented = false;
        const target = { closest: (selector) => (selector.includes("signin") ? {} : null) };
        page.listeners.click[0]({ target, preventDefault: () => { prevented = true; } });
        assert.ok(prevented, "the sign-in lock does not follow a link");
        assert.strictEqual(page.logins.length, 1, "the sign-in lock asks oidc.js for the PKCE login");
      } else if (scenario === "denied") {
        const page = mount({ api: true, reply: null });
        page.emit("dashboard:identity", { groups: [] });
        const [lock] = page.chips["web-app-gated"];
        assert.strictEqual(lock.state, "denied");
        assert.strictEqual(lock.href, undefined, "without the access request service the lock links nowhere");
      } else if (scenario === "health") {
        const reply = { applications: {
          "web-app-gated": { state: "paused", checked: now, code: 503 },
          "web-app-open": { state: "running", checked: "2000-01-01T00:00:00+00:00", code: 200 },
        } };
        const page = mount({ api: true, reply });
        await settle();
        assert.deepStrictEqual(page.fetches, ["/status.json"]);
        assert.deepStrictEqual(page.intervals, [60000]);
        const [paused] = page.chips["web-app-gated"];
        assert.strictEqual(paused.state, "paused");
        assert.strictEqual(paused.tone, "info");
        assert.strictEqual(paused.icon, "fa-solid fa-circle-pause", "port-ui takes the full Font Awesome class list");
        assert.match(paused.detail, /^ · /, "the badge names the check time");
        assert.deepStrictEqual(states(page.chips["web-app-open"]), ["health:unknown"], "a stale entry is unknown");
        page.emit("dashboard:identity", { groups: null });
        assert.deepStrictEqual(states(page.chips["web-app-gated"]), ["health:paused"], "locks switched off");
      } else if (scenario === "offline") {
        const page = mount({ api: true, reply: null });
        await settle();
        assert.deepStrictEqual(states(page.chips["web-app-gated"]), ["health:unknown"]);
        assert.deepStrictEqual(states(page.chips["web-app-open"]), ["health:unknown"]);
      } else if (scenario === "late") {
        const page = mount({ api: false, reply: null });
        assert.deepStrictEqual(page.chips, {}, "nothing is set before port-ui offers its chip API");
        global.window.portui = page.portui;
        page.emit("portui:ready");
        page.emit("dashboard:identity", { groups: null });
        assert.deepStrictEqual(states(page.chips["web-app-gated"]), ["lock:signin"]);
      }
      console.log("OK");
    })().catch((error) => { console.error(error); process.exit(1); });
    """
).replace("GATE_PATH", json.dumps(GATE))


def _render(*, locks: bool, status: bool, request: bool) -> str:
    env = Environment(
        loader=FileSystemLoader(str(ROLE)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = lambda value: json.dumps(value, ensure_ascii=False)
    env.filters["bool"] = bool
    env.filters["items2dict"] = lambda items, key_name, value_name: {
        item[key_name]: item[value_name] for item in items
    }
    return env.get_template(TEMPLATE).render(
        lookup=lambda name, *_: CARDS if name == "docker_cards" else None,
        DASHBOARD_LOCKS_ENABLED=locks,
        DASHBOARD_ACCESS_REQUEST_ENABLED=request,
        DASHBOARD_ACCESS_REQUEST_URL="https://access.example.test/?application={id}",
        DASHBOARD_STATUS_ENABLED=status,
        DASHBOARD_STATUS_PATH="/status.json",
        DASHBOARD_STATUS_POLL_SECONDS="60",
        DASHBOARD_STATUS_STALE_AFTER_SECONDS="3600",
    )


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestChips(unittest.TestCase):
    def _run(self, scenario: str, **switches: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "chips.js"
            script.write_text(_render(**switches))
            driver = Path(tmp) / "driver.js"
            driver.write_text(DRIVER)
            proc = subprocess.run(
                ["node", str(driver), str(script), scenario],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("OK", proc.stdout)

    def test_locks_follow_the_identity_and_offer_the_access_request(self) -> None:
        self._run("locks", locks=True, status=False, request=True)

    def test_a_lock_without_the_access_request_service_links_nowhere(self) -> None:
        self._run("denied", locks=True, status=False, request=False)

    def test_badges_show_fresh_states_and_stale_entries_as_unknown(self) -> None:
        self._run("health", locks=False, status=True, request=False)

    def test_an_unreachable_status_document_leaves_every_badge_unknown(self) -> None:
        self._run("offline", locks=False, status=True, request=False)

    def test_chips_wait_for_the_port_ui_chip_api(self) -> None:
        self._run("late", locks=True, status=False, request=False)


if __name__ == "__main__":
    unittest.main()
