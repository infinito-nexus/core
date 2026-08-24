const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const PANEL = path.join(
  PROJECT_ROOT,
  "roles/web-app-keycloak/files/javascript/logout-panel.js",
);
const CATALOGUE = path.join(
  PROJECT_ROOT,
  "roles/web-app-keycloak/files/logout_i18n.yml",
);
const ORIGIN = "https://logout.example.test";
const DOMAINS = ["https://shop.example.test", "https://cloud.example.test"];

/**
 * Read the catalogue without a YAML dependency.
 *
 * The file is generated, flat and two levels deep, so a line reader is enough
 * and keeps this suite free of a parser it would otherwise need for one file.
 */
function readCatalogue() {
  const out = {};
  let current = null;
  for (const line of fs.readFileSync(CATALOGUE, "utf8").split("\n")) {
    const top = line.match(/^([a-z]{2}):\s*$/);
    if (top) {
      current = {};
      out[top[1]] = current;
      continue;
    }
    const entry = line.match(/^ {2}([a-z_]+):\s*(.*)$/);
    if (entry && current) {
      let value = entry[2].trim();
      if (
        (value.startsWith("'") && value.endsWith("'")) ||
        (value.startsWith('"') && value.endsWith('"'))
      ) {
        value = value.slice(1, -1).replace(/''/g, "'");
      }
      current[entry[1]] = value;
    }
  }
  return out;
}

function element() {
  const node = {
    children: [],
    style: { cssText: "" },
    attrs: {},
    id: "",
    title: "",
    href: "",
    setAttribute(key, value) {
      this.attrs[key] = value;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
  };
  let text = "";
  Object.defineProperty(node, "textContent", {
    get: () => text,
    set(value) {
      text = value;
      node.children.length = 0;
    },
    enumerable: true,
  });
  return node;
}

/** Load the panel against a stubbed page and return handles for assertions. */
function mount({ lang = "en", hostname = "auth.example.test", path: pathname = "/realms/x/protocol/openid-connect/logout" } = {}) {
  const body = element();
  const listeners = {};
  const timers = {};
  let next = 0;

  global.window = {
    __INFINITO_LOGOUT__: { origin: ORIGIN, i18n: readCatalogue() },
    location: { pathname, hostname },
    addEventListener(type, fn) {
      listeners[type] = listeners[type] || [];
      if (!listeners[type].includes(fn)) listeners[type].push(fn);
    },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
  };
  global.document = {
    readyState: "complete",
    createElement: element,
    querySelector: () => null,
    getElementById: () => null,
    documentElement: { lang },
    body,
    addEventListener() {},
  };
  Object.defineProperty(globalThis, "navigator", {
    value: { language: "en" },
    configurable: true,
    writable: true,
  });
  global.setTimeout = (fn, ms) => {
    next += 1;
    timers[next] = { fn, ms };
    return next;
  };
  global.clearTimeout = (id) => {
    if (id && timers[id]) timers[id].cleared = true;
  };

  // eslint-disable-next-line no-eval
  eval(fs.readFileSync(PANEL, "utf8"));

  const post = (payload) =>
    (listeners.message || []).forEach((fn) =>
      fn({ origin: ORIGIN, data: { source: "universal-logout", ...payload } }),
    );
  const panel = () => body.children[0];
  return {
    post,
    panel,
    status: () => panel().children[0].textContent,
    hint: () => panel().children[1].textContent,
    counter: () => panel().children[2].textContent,
    rows: () => panel().children[3].children,
    armed: () => (listeners.beforeunload || []).length,
    live: (ms) =>
      Object.values(timers).filter((t) => t.ms === ms && !t.cleared),
  };
}

test("the catalogue reader sees every language", () => {
  const catalogue = readCatalogue();
  assert.equal(Object.keys(catalogue).length, 30);
  assert.equal(catalogue.de.dir, "ltr");
  assert.equal(catalogue.ar.dir, "rtl");
});

test("a clean sweep ends by telling the visitor they may leave", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.status(), /Signing you out/);
  assert.equal(page.armed(), 1);

  page.post({ type: "host", host: DOMAINS[0], ok: true });
  page.post({ type: "host", host: DOMAINS[1], ok: true });
  page.post({ type: "done", total: 2, failed: 0 });

  assert.match(page.status(), /Signed out everywhere/);
  assert.match(page.hint(), /You can close this page now/);
  assert.equal(page.counter(), "2 of 2 services signed out");
  assert.equal(page.armed(), 0, "the guard is released once the sweep is done");
});

test("a failing host keeps a way out on screen", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  page.post({ type: "host", host: DOMAINS[1], ok: false });

  const right = page.rows()[1].children[1];
  assert.match(right.children[0].textContent, /failed/);
  assert.equal(right.children[1].href, `${DOMAINS[1]}/logout?manual=1`);
});

test("the panel speaks the language Keycloak chose", () => {
  const page = mount({ lang: "de" });
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.status(), /Sie werden von Ihren Diensten abgemeldet/);

  page.post({ type: "host", host: DOMAINS[0], ok: true });
  assert.equal(page.counter(), "1 von 2 Diensten abgemeldet");
});

test("right-to-left languages flip the panel", () => {
  const page = mount({ lang: "ar" });
  page.post({ type: "start", domains: DOMAINS });
  assert.equal(page.panel().attrs.dir, "rtl");
});

test("an unknown language falls back to English", () => {
  const page = mount({ lang: "klingon" });
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.status(), /Signing you out/);
});

test("onion sessions are told to expect a longer wait", () => {
  const page = mount({ hostname: "abcdefghij.onion" });
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.hint(), /Over Tor this can take a while/);
});

test("a sweep that stalls says so instead of spinning forever", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  page.post({ type: "host", host: DOMAINS[0], ok: true });

  const [sweep] = page.live(60000);
  assert.ok(sweep, "the stall timer is armed on start");
  sweep.fn();

  assert.match(page.status(), /Could not confirm every sign-out/);
  assert.doesNotMatch(page.status(), /Signed out everywhere/);
  assert.equal(page.armed(), 0, "the guard fails open");
});

test("the panel stays off every other Keycloak page", () => {
  const page = mount({ path: "/realms/x/account" });
  assert.equal(page.armed(), 0);
});
