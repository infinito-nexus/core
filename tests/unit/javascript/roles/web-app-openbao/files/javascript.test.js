const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..", "..", "..", "..", "..", "..",
  "roles", "web-app-openbao", "files", "javascript", "javascript.js",
);
const REVOKE_PATH = "/v1/auth/token/revoke-self";

function fakeStorage(entries) {
  const items = new Map(Object.entries(entries));
  return {
    get length() {
      return items.size;
    },
    key: (index) => [...items.keys()][index] ?? null,
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    removeItem: (key) => {
      items.delete(key);
    },
    keys: () => [...items.keys()],
  };
}

function loadHook({ pathname = "/ui/vault/secrets", local = {}, session = {}, blockLocal = false } = {}) {
  const revokes = [];
  const listeners = [];
  const window = {
    sessionStorage: fakeStorage(session),
    location: { pathname },
    fetch: (url, init) => {
      revokes.push({ url, method: init.method, token: init.headers["X-Vault-Token"], keepalive: init.keepalive });
      return Promise.resolve({ ok: true });
    },
    addEventListener: (type, handler, capture) => listeners.push({ type, handler, capture }),
  };
  const localStorage = fakeStorage(local);
  Object.defineProperty(window, "localStorage", {
    get() {
      if (blockLocal) throw new Error("storage denied");
      return localStorage;
    },
  });
  vm.runInNewContext(fs.readFileSync(SOURCE, "utf8"), { window });
  return { revokes, listeners, local: localStorage, session: window.sessionStorage };
}

function click(listeners, insideLogout) {
  const selectors = [];
  const target = {
    closest: (selector) => {
      selectors.push(selector);
      return insideLogout ? {} : null;
    },
  };
  for (const listener of listeners.filter(({ type }) => type === "click")) listener.handler({ target });
  return selectors;
}

const TOKENS = {
  local: { "vault-token☃1": JSON.stringify({ token: "s.local" }), "vault-console-history": "[]", other: "keep" },
  session: { "vault-token☃2": JSON.stringify({ token: "s.session" }) },
};

test("a click on the logout control revokes every stored token before the page leaves and clears the vault storage", () => {
  const { revokes, listeners, local, session } = loadHook(TOKENS);
  assert.deepEqual(
    listeners.map(({ type, capture }) => [type, capture]),
    [["click", true]],
  );

  const selectors = click(listeners, true);

  assert.ok(selectors[0].split(",").map((part) => part.trim()).includes("#logout"));
  assert.deepEqual(revokes, [
    { url: REVOKE_PATH, method: "POST", token: "s.local", keepalive: true },
    { url: REVOKE_PATH, method: "POST", token: "s.session", keepalive: true },
  ]);
  assert.deepEqual(local.keys(), ["other"]);
  assert.deepEqual(session.keys(), []);
});

test("a click anywhere else leaves the session alone", () => {
  const { revokes, listeners, local, session } = loadHook(TOKENS);

  click(listeners, false);

  assert.deepEqual(revokes, []);
  assert.equal(local.keys().length, 3);
  assert.equal(session.keys().length, 1);
});

test("opening the logout route ends the session before the app boots", () => {
  const { revokes, local, session } = loadHook({ ...TOKENS, pathname: "/ui/vault/logout" });

  assert.deepEqual(
    revokes.map(({ token }) => token),
    ["s.local", "s.session"],
  );
  assert.deepEqual(local.keys(), ["other"]);
  assert.deepEqual(session.keys(), []);
});

test("a stored value without a token is cleared without a revoke", () => {
  const { revokes, listeners, local } = loadHook({ local: { "vault-broken": "not json", "vault-empty": "{}" } });

  click(listeners, true);

  assert.deepEqual(revokes, []);
  assert.deepEqual(local.keys(), []);
});

test("a browser that refuses one storage still ends the session in the other", () => {
  const { revokes, listeners, session } = loadHook({ ...TOKENS, blockLocal: true });

  click(listeners, true);

  assert.deepEqual(
    revokes.map(({ token }) => token),
    ["s.session"],
  );
  assert.deepEqual(session.keys(), []);
});
