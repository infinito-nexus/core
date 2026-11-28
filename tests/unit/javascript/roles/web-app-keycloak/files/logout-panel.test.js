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
const EVERYWHERE = "https://dashboard.example.test/#logout-everywhere";
const DOMAINS = ["https://shop.example.test", "https://cloud.example.test"];
const SIBLING = `http://logout.${"a".repeat(56)}.onion/?handoff=`;
const TOR_SUFFIX = ".onion";

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

/**
 * The stock confirmation form Keycloak renders without the corporate theme.
 *
 * Args:
 *   withEverywhere: also render the "Log out everywhere" link the corporate theme adds.
 */
function confirmationPage(withEverywhere = false) {
  const placed = [];
  const form = {
    insertAdjacentElement(where, node) {
      placed.push({ where, node });
      return node;
    },
  };
  const confirm = {
    tagName: "INPUT",
    id: "kc-logout",
    value: "Sign out",
    className: "pf-v5-c-button pf-v5-c-button pf-m-primary pf-m-block",
    form,
  };
  const byId = { "kc-logout": confirm };
  if (withEverywhere) {
    byId["kc-logout-everywhere"] = { tagName: "A", id: "kc-logout-everywhere" };
  }
  return { byId, confirm, placed };
}

/** Load the panel against a stubbed page and return handles for assertions. */
function mount({
  lang = "en",
  hostname = "auth.example.test",
  path: pathname = "/realms/x/protocol/openid-connect/logout",
  everywhere = EVERYWHERE,
  torSuffix = TOR_SUFFIX,
  byId = {},
} = {}) {
  const body = element();
  const listeners = {};
  const timers = {};
  const visited = [];
  let next = 0;

  global.window = {
    __INFINITO_LOGOUT__: {
      origin: ORIGIN,
      everywhere,
      tor_suffix: torSuffix,
      i18n: readCatalogue(),
    },
    location: { pathname, hostname, replace: (url) => visited.push(url) },
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
    getElementById: (id) => byId[id] || null,
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
  const send = (origin, data) =>
    (listeners.message || []).forEach((fn) => fn({ origin, data }));
  const panel = () => body.children[0];
  return {
    post,
    send,
    visited,
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

  assert.match(page.status(), /Signed out on this device/);
  assert.doesNotMatch(page.status(), /everywhere/, "a sweep of this browser must not claim every device");
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

test("the longer wait follows the tor suffix the server renders", () => {
  const page = mount({ hostname: "auth.example.test", torSuffix: ".example.test" });
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.hint(), /Over Tor this can take a while/);
});

test("without a rendered tor suffix no host gets the longer wait", () => {
  const page = mount({ hostname: "abcdefghij.onion", torSuffix: "" });
  page.post({ type: "start", domains: DOMAINS });
  assert.match(page.hint(), /This usually takes a few seconds/);
});

test("a sweep that stalls says so instead of spinning forever", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  page.post({ type: "host", host: DOMAINS[0], ok: true });

  const [sweep] = page.live(60000);
  assert.ok(sweep, "the stall timer is armed on start");
  sweep.fn();

  assert.match(page.status(), /Could not confirm every sign-out/);
  assert.doesNotMatch(page.status(), /Signed out on this device/);
  assert.equal(page.armed(), 0, "the guard fails open");
});

test("the panel stays off every other Keycloak page", () => {
  const page = mount({ path: "/realms/x/account" });
  assert.equal(page.armed(), 0);
});

test("without the corporate theme the confirmation page still offers both choices", () => {
  const stock = confirmationPage();
  mount({ byId: stock.byId });

  assert.equal(stock.confirm.value, "Log out on this device");
  assert.equal(stock.placed.length, 1, "exactly one link joins the form");
  const { where, node } = stock.placed[0];
  assert.equal(where, "afterend");
  assert.equal(node.id, "kc-logout-everywhere");
  assert.equal(node.href, EVERYWHERE);
  assert.equal(node.textContent, "Log out everywhere");
  assert.match(node.className, /pf-m-secondary/);
  assert.doesNotMatch(node.className, /pf-m-primary/, "the device submit stays the primary action");
});

test("the everywhere link carries nothing but the marker", () => {
  const stock = confirmationPage();
  mount({ byId: stock.byId });

  const url = new URL(stock.placed[0].node.href);
  assert.equal(url.search, "", "no query parameter may ride along");
  assert.equal(url.hash, "#logout-everywhere");
});

test("the confirmation page is a choice, not a sweep in progress", () => {
  const stock = confirmationPage();
  const page = mount({ byId: stock.byId });

  assert.equal(page.panel(), undefined, "no status is painted before the visitor chose");
  assert.equal(page.armed(), 0, "no unload guard may hold either choice back");
  assert.equal(page.live(20000).length, 0, "no grace timer turns the choice into a failure");
});

test("the choices speak the visitor's language", () => {
  const stock = confirmationPage();
  mount({ lang: "de", byId: stock.byId });

  const catalogue = readCatalogue();
  assert.equal(stock.confirm.value, catalogue.de.choice_device);
  assert.equal(stock.placed[0].node.textContent, catalogue.de.choice_everywhere);
});

test("without the dashboard the confirmation page offers no everywhere link", () => {
  const stock = confirmationPage();
  const page = mount({ everywhere: "", byId: stock.byId });

  assert.equal(stock.placed.length, 0);
  assert.equal(stock.confirm.value, "Sign out", "the stock submit keeps its label");
  assert.equal(page.armed(), 0);
});

test("the corporate theme's own choices are left as rendered", () => {
  const themed = confirmationPage(true);
  mount({ byId: themed.byId });

  assert.equal(themed.placed.length, 0, "the server-side link is not duplicated");
  assert.equal(themed.confirm.value, "Sign out");
});

test("a hand-off moves the whole page to the next network's conductor", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  page.post({ type: "host", host: DOMAINS[0], ok: true });
  page.post({ type: "host", host: DOMAINS[1], ok: true });
  page.post({ type: "done", total: 2, failed: 0 });
  page.post({ type: "handoff", url: SIBLING });

  assert.deepEqual(page.visited, [SIBLING]);
});

test("a hand-off is not held back by the unload guard", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  assert.equal(page.armed(), 1);

  page.post({ type: "handoff", url: SIBLING });

  assert.deepEqual(page.visited, [SIBLING]);
  assert.equal(page.armed(), 0, "a guard left armed would stop the navigation with a leave-page prompt");
});

test("only the conductor can hand the page off", () => {
  const page = mount();
  page.send("https://evil.test", { source: "universal-logout", type: "handoff", url: SIBLING });
  page.send(ORIGIN, { type: "handoff", url: SIBLING });

  assert.deepEqual(page.visited, []);
});

test("a hand-off to anything but an absolute http(s) URL is ignored", () => {
  const page = mount();
  page.post({ type: "start", domains: DOMAINS });
  for (const url of ["javascript:alert(1)", "data:text/html,x", "/realms/x", "", undefined]) {
    page.post({ type: "handoff", url });
  }

  assert.deepEqual(page.visited, []);
  assert.equal(page.armed(), 1, "a refused hand-off leaves the sweep guarded");
});
