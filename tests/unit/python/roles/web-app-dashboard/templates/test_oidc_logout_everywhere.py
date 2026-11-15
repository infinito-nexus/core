"""The dashboard's two logout choices, run against a fake Keycloak adapter.

The template is rendered the way the role deploys it, then driven in Node with
a stubbed page, ``fetch`` and adapter, so the order of the Account REST calls
and the outcome after every failure are checked without a browser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import urllib.parse
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any, load_yaml_str
from utils.i18n.extract import logout_context
from utils.i18n.keyed import keyed_catalogue
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-dashboard"
TEMPLATE = "templates/javascript/oidc.js.j2"
MENU = "templates/menu/header.yml.j2"
CATALOGUE = PROJECT_ROOT / "roles" / "web-app-keycloak" / "files" / "logout_i18n.yml"
DASHBOARD = "https://dashboard.example.test/"
KEYCLOAK = "https://auth.example.test"
REALM = "example.test"
ADAPTER = "data:text/javascript," + urllib.parse.quote(
    "export default function Keycloak(config) { return globalThis.__fakeKeycloak(config); }"
)

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const ACCOUNT = process.argv[3];
    const CLIENT_ID = process.argv[4];
    const DEVICE_ICON = process.argv[5];
    const EVERYWHERE_ICON = process.argv[6];

    function storage(seed) {
      const values = new Map(Object.entries(seed || {}));
      return {
        values,
        getItem: (k) => (values.has(k) ? values.get(k) : null),
        setItem: (k, v) => values.set(k, String(v)),
        removeItem: (k) => values.delete(k),
      };
    }

    async function mount({ authenticated = true, hash = "", stored = {}, answer = () => ({ ok: true, status: 204 }) } = {}) {
      const calls = [];
      const listeners = {};
      const prepended = [];
      const kc = {
        authenticated, token: "user-token", tokenParsed: null, logouts: [], logins: [],
        init: async () => authenticated,
        updateToken: async () => true,
        logout(options) { this.logouts.push(options); return Promise.resolve(); },
        login(options) { this.logins.push(options); return Promise.resolve(); },
      };
      globalThis.__fakeKeycloak = (config) => { kc.config = config; return kc; };
      global.sessionStorage = storage(stored);
      global.history = { replaceState: (_s, _t, url) => { global.window.location.hash = ""; calls.push(["replace", url]); } };
      global.window = {
        location: { hash, pathname: "/", search: "" },
        addEventListener(type, fn, options) { (listeners[type] = listeners[type] || []).push({ fn, options }); },
      };
      global.document = {
        readyState: "complete",
        documentElement: { lang: "en" },
        querySelectorAll: () => [],
        querySelector: () => null,
        createElement: () => ({ setAttribute(k, v) { this[k] = v; } }),
        body: { prepend: (node) => prepended.push(node) },
        dispatchEvent: () => true,
        addEventListener() {},
      };
      global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
      Object.defineProperty(globalThis, "navigator", { value: { language: "en" }, configurable: true, writable: true });
      global.fetch = async (url, init) => {
        calls.push([init.method, url.replace(ACCOUNT, ""), init.headers.Authorization]);
        const reply = await answer(init.method, url.replace(ACCOUNT, ""));
        return { ok: reply.ok, status: reply.status, json: async () => reply.body };
      };
      (0, eval)(script);
      await settle();
      return { kc, calls, listeners, prepended, store: global.sessionStorage.values };
    }

    async function settle() {
      for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
    }

    function click(page, iconClasses) {
      const classes = iconClasses.split(" ");
      const link = { querySelector: (selector) => (classes.includes(selector.replace(/^\\./, "")) ? {} : null) };
      const ev = { target: { closest: () => link }, prevented: false, stopped: false };
      ev.preventDefault = () => { ev.prevented = true; };
      ev.stopPropagation = () => { ev.stopped = true; };
      const capture = page.listeners.click.filter((l) => l.options && l.options.capture);
      assert.strictEqual(capture.length, 1, "one capture listener on window watches the Account menu");
      capture[0].fn(ev);
      return ev;
    }

    const APPLICATIONS = [
      { clientId: "mobile", offlineAccess: true },
      { clientId: "web", offlineAccess: false },
    ];

    (async () => {
      {
        const page = await mount({
          answer: (method, path) => (method === "GET" ? { ok: true, status: 200, body: APPLICATIONS } : { ok: true, status: 204 }),
        });
        const ev = click(page, EVERYWHERE_ICON);
        await settle();
        assert.ok(ev.prevented && ev.stopped, "the injected logout patch never sees the click");
        assert.deepStrictEqual(
          page.calls.map(([method, path]) => method + " " + path),
          ["GET /applications", "DELETE /applications/mobile/consent", "DELETE /sessions"],
          "offline tokens first, then every other session",
        );
        assert.ok(page.calls.every(([, , auth]) => auth === "Bearer user-token"), "only the user's own token is sent");
        assert.strictEqual(page.store.get("infinito-logout-result"), "everywhere");
        assert.strictEqual(page.kc.logouts.length, 1, "then this device logs out");
        assert.strictEqual(page.kc.config.clientId, CLIENT_ID, "the token holder is the dashboard's own client");
      }
      {
        const page = await mount({
          answer: (method, path) =>
            method === "GET" ? { ok: true, status: 200, body: [] } : path === "/sessions" ? { ok: false, status: 500 } : { ok: true, status: 204 },
        });
        click(page, EVERYWHERE_ICON);
        await settle();
        assert.strictEqual(page.store.get("infinito-logout-result"), "partial");
        assert.strictEqual(page.kc.logouts.length, 1, "a refused DELETE still logs this device out");
      }
      {
        const page = await mount({ answer: () => { throw new TypeError("Failed to fetch"); } });
        click(page, EVERYWHERE_ICON);
        await settle();
        assert.strictEqual(page.store.get("infinito-logout-result"), "partial");
        assert.strictEqual(page.kc.logouts.length, 1, "a blocked request still logs this device out");
      }
      {
        const page = await mount();
        const ev = click(page, DEVICE_ICON);
        await settle();
        assert.ok(!ev.prevented, "Log out on this device navigates to the confirmation page");
        assert.ok(!ev.stopped, "and the injected logout patch may still align its URL");
        assert.strictEqual(page.kc.logouts.length, 0, "keycloak-js sends no id_token_hint");
        assert.strictEqual(page.kc.logins.length, 0);
        assert.deepStrictEqual(page.calls.filter((c) => c[0] !== "replace"), [], "this device sends no Account call");
        assert.ok(!page.store.has("infinito-logout-result"));
      }
      {
        const page = await mount({ authenticated: true, hash: "#logout-everywhere" });
        await settle();
        assert.deepStrictEqual(page.calls[0], ["replace", "/"], "the marker leaves the address bar");
        assert.strictEqual(page.kc.logouts.length, 1, "the marker runs the everywhere choice");
      }
      {
        const page = await mount({ authenticated: false, hash: "#logout-everywhere" });
        assert.strictEqual(page.kc.logins.length, 1, "without a session the dashboard signs in first");
        assert.strictEqual(page.store.get("infinito-logout-pending"), "everywhere");
        assert.strictEqual(page.kc.logouts.length, 0);
      }
      {
        const page = await mount({ authenticated: true, stored: { "infinito-logout-pending": "everywhere" } });
        assert.strictEqual(page.kc.logouts.length, 1, "the choice runs after the sign-in returns");
        assert.ok(!page.store.has("infinito-logout-pending"));
      }
      {
        const page = await mount({ authenticated: false, stored: { "infinito-logout-result": "partial" } });
        assert.strictEqual(page.prepended.length, 1, "the outcome is shown after the redirect");
        assert.strictEqual(page.prepended[0].role, "alert");
        assert.match(page.prepended[0].textContent, /Other devices may still be signed in/);
        assert.ok(!page.store.has("infinito-logout-result"), "and only once");
      }
      {
        const page = await mount({ authenticated: false, stored: { "infinito-logout-result": "everywhere" } });
        assert.strictEqual(page.prepended[0].role, "status");
        assert.match(page.prepended[0].textContent, /Signed out everywhere/);
      }
      console.log("OK");
    })().catch((error) => { console.error(error); process.exit(1); });
    """
)


def _services(path: str):
    node = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
    for key in path.removeprefix("services.").split("."):
        node = node[key]
    return node


CLIENT_ID = _services("services.sso.oidc.clients.dashboard")


def _lookup(name, *args, **_kwargs):
    if name == "config" and args[1] == "services.tor.enabled":
        return False
    if name == "debug" and not args:
        return False
    if name == "tls":
        return DASHBOARD.rstrip("/")
    if name == "asset":
        return ADAPTER
    raise AssertionError(f"unexpected lookup {name}{args}")


LOGOUT_URL = f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/logout"
LOGOUT_I18N = keyed_catalogue(
    PROJECT_ROOT, logout_context, load_yaml(CATALOGUE), PROJECT_ROOT, "core"
)


def _context() -> dict:
    role_vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
    return {
        "lookup": _lookup,
        "application_id": "web-app-dashboard",
        "domain": "dashboard.example.test",
        "ORGANIZATION": "Example",
        "DOMAIN_PRIMARY": "example.test",
        "OIDC": {
            "URL": KEYCLOAK,
            "CLIENT": {
                "REALM": REALM,
                "ID": REALM,
                "LOGOUT_URL": LOGOUT_URL,
                "ACCOUNT": {
                    "PROFILE_URL": f"{KEYCLOAK}/realms/{REALM}/account/#/personal-info",
                    "SECURITY_URL": f"{KEYCLOAK}/realms/{REALM}/account/#/security",
                },
            },
        },
        "DASHBOARD_APP_BASE_URL": DASHBOARD,
        "DASHBOARD_APPLICATION_ID": "web-app-dashboard",
        "DASHBOARD_OIDC_ENABLED": True,
        "DASHBOARD_KEYCLOAK_IFRAME_ENABLED": False,
        "DASHBOARD_KEYCLOAK_LOGIN_URL": f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/auth",
        "DASHBOARD_OIDC_CLIENT_ID": CLIENT_ID,
        "DASHBOARD_LOCATION_SILENT_CHECK": role_vars["DASHBOARD_LOCATION_SILENT_CHECK"],
        "DASHBOARD_LOGOUT_EVERYWHERE_MARKER": _services(
            "services.sso.oidc.logout_everywhere"
        ),
        "DASHBOARD_LOGOUT_EVERYWHERE_CLASS": role_vars[
            "DASHBOARD_LOGOUT_EVERYWHERE_CLASS"
        ],
        "DASHBOARD_LOGOUT_I18N": LOGOUT_I18N,
        "RBAC": {"GROUP": {"CLAIM": "groups"}},
    }


def _render(template: str) -> str:
    env = Environment(
        loader=FileSystemLoader(str(ROLE)),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = lambda value: json.dumps(value, ensure_ascii=False)
    env.filters["bool"] = bool
    env.filters["network_of"] = lambda _domain: "clearnet"
    return env.get_template(template).render(**_context())


def _account_items() -> dict[str, dict]:
    """Return the Account menu items of the rendered header, keyed by name."""
    header = load_yaml_str(_render(MENU))["header"]["children"]
    account = next(item for item in header if item.get("name") == "Account")
    return {item["name"]: item for item in account["children"]}


DEVICE_ITEM = _account_items()[LOGOUT_I18N["en"]["choice_device"]]
EVERYWHERE_ITEM = _account_items()[LOGOUT_I18N["en"]["choice_everywhere"]]


class TestAccountMenuChoices(unittest.TestCase):
    def test_this_device_is_a_plain_link_to_the_confirmation_page(self) -> None:
        self.assertEqual(DEVICE_ITEM["url"], LOGOUT_URL)
        self.assertNotIn("id_token_hint", DEVICE_ITEM["url"])
        self.assertEqual(DEVICE_ITEM["target"], "_top")
        self.assertNotIn("onclick", DEVICE_ITEM)

    def test_this_device_carries_no_marker_the_dashboard_intercepts(self) -> None:
        self.assertNotIn(
            _context()["DASHBOARD_LOGOUT_EVERYWHERE_CLASS"],
            DEVICE_ITEM["icon"]["class"].split(),
        )

    def test_everywhere_leads_to_the_dashboard_marker(self) -> None:
        self.assertEqual(
            EVERYWHERE_ITEM["url"],
            DASHBOARD + _services("services.sso.oidc.logout_everywhere"),
        )
        self.assertIn(
            _context()["DASHBOARD_LOGOUT_EVERYWHERE_CLASS"],
            EVERYWHERE_ITEM["icon"]["class"].split(),
        )


@unittest.skipUnless(shutil.which("node"), "node is not available in PATH")
class TestDashboardLogoutChoices(unittest.TestCase):
    def test_both_choices_end_the_sessions_they_name_and_fail_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "oidc.js"
            script.write_text(_render(TEMPLATE))
            driver = Path(tmp) / "driver.js"
            driver.write_text(DRIVER)
            proc = subprocess.run(
                [
                    "node",
                    str(driver),
                    str(script),
                    f"{KEYCLOAK}/realms/{REALM}/account",
                    CLIENT_ID,
                    DEVICE_ITEM["icon"]["class"],
                    EVERYWHERE_ITEM["icon"]["class"],
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
