const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const BASE = "https://shop.example";
const DOTENV = {
  APP_BASE_URL: BASE,
  ADMIN_USERNAME: "administrator",
  ADMIN_PASSWORD: "administrator-secret",
  CANONICAL_DOMAIN: "shop.example",
};
const RESPONSES = {
  "/api/oauth/token": { access_token: "token" },
  "/api/search/sales-channel": { data: [{ id: "channel", domains: [{ url: BASE }] }] },
  "/api/search/tax": { data: [{ id: "tax", taxRate: 19 }] },
  "/api/search/theme": { data: [{ id: "theme" }] },
  "/api/search/salutation": { data: [{ id: "salutation" }] },
  "/api/_action/sync": {},
};
const passes = new Proxy(
  {},
  {
    get: (_, matcher) => {
      if (matcher === "then") return undefined;
      return matcher === "not" ? passes : async () => undefined;
    },
  },
);

const synced = [];
const { seedShowcase, signInCustomer } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-shopware/files/playwright/test-design.js"),
  ["seedShowcase", "signInCustomer"],
  {
    "node:crypto": { ...crypto, randomBytes: (size) => Buffer.alloc(size, 0x5a) },
    "@playwright/test": { test: () => undefined, expect: () => passes },
    "./personas": {
      apiFetchOnion: async (_request, url, options) => {
        const route = url.slice(BASE.length);
        if (route === "/api/_action/sync") synced.push(options.data);
        return { status: () => 200, json: async () => RESPONSES[route] };
      },
      decodeDotenvQuotedValue: (value) => value,
      gotoOnion: async () => undefined,
      normalizeBaseUrl: (value) => value,
      requireDotenvValue: (_value, name) => DOTENV[name],
    },
    "./timeouts": { resolveTimeout: (ms) => ms },
  },
  {},
);

test("the showcase customer signs in with a password drawn from node:crypto, not derived from the administrator's", async () => {
  await seedShowcase({});
  const filled = {};
  const locator = (selector) => ({
    fill: async (value) => {
      filled[selector] = value;
    },
    locator,
    press: async () => undefined,
  });
  await signInCustomer({ locator });

  const seeded = synced[0]["design-showcase-customer"].payload[0].password;
  assert.match(seeded, /^(?:5a){16,}$/);
  assert.equal(filled["input[name='password']"], seeded);
});
