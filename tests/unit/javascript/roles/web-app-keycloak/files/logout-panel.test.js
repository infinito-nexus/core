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
const LOCALE = path.join(PROJECT_ROOT, "locale");
const LANGUAGES = path.join(PROJECT_ROOT, "meta/languages.yml");
const ORIGIN = "https://logout.example.test";
const DOMAINS = ["https://shop.example.test", "https://cloud.example.test"];

function readEnglish() {
  const out = {};
  for (const line of fs.readFileSync(CATALOGUE, "utf8").split("\n")) {
    const entry = line.match(/^([a-z_]+):\s*(".*")$/);
    if (entry) {
      out[entry[1]] = JSON.parse(entry[2]);
    }
  }
  return out;
}

function readDirections() {
  const out = {};
  let code = null;
  for (const line of fs.readFileSync(LANGUAGES, "utf8").split("\n")) {
    const top = line.match(/^"?([a-z]{2})"?:\s*$/);
    if (top) {
      code = top[1];
    }
    const direction = line.match(/^ {2}direction: (ltr|rtl)$/);
    if (direction && code) {
      out[code] = direction[1];
    }
  }
  return out;
}

function readPo(file) {
  const entries = [];
  let current = null;
  let field = null;
  let fuzzy = false;
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (line.startsWith("#,")) {
      fuzzy = line.includes("fuzzy");
      continue;
    }
    const start = line.match(/^(msgctxt|msgid|msgstr) (".*")$/);
    if (start) {
      if (start[1] === "msgctxt" || (start[1] === "msgid" && (!current || "msgstr" in current))) {
        current = { fuzzy };
        entries.push(current);
        fuzzy = false;
      }
      field = start[1];
      current[field] = JSON.parse(start[2]);
    } else if (line.startsWith('"') && current && field) {
      current[field] += JSON.parse(line);
    }
  }
  return entries;
}

function readCatalogue() {
  const english = readEnglish();
  const directions = readDirections();
  const out = { en: { ...english, dir: directions.en } };
  for (const code of fs.readdirSync(LOCALE).sort()) {
    const file = path.join(LOCALE, code, "LC_MESSAGES", "core.po");
    if (!fs.existsSync(file)) {
      continue;
    }
    const found = {};
    for (const entry of readPo(file)) {
      const key = (entry.msgctxt || "").replace(/^logout:/, "");
      if (entry.msgctxt === `logout:${key}` && entry.msgid === english[key] && entry.msgstr && !entry.fuzzy) {
        found[key] = entry.msgstr;
      }
    }
    if (Object.keys(found).length > 0) {
      out[code] = { ...english, ...found, dir: directions[code] };
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
  assert.ok(Object.keys(catalogue).length >= 30);
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
