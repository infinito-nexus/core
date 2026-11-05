const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const CSPRNG_UUID = "6f1c2a3e-0b4d-4e5f-8a9b-0c1d2e3f4a5b";
const PASSWORD = "#loginform input#password";
const passes = new Proxy(
  {},
  {
    get: (_, matcher) => {
      if (matcher === "then") return undefined;
      return matcher === "not" ? passes : async () => undefined;
    },
  },
);

const { galleryViews } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-fusiondirectory/files/playwright/test-design.js"),
  ["galleryViews"],
  {
    "node:crypto": { randomUUID: () => CSPRNG_UUID },
    "@playwright/test": { test: { skip: () => undefined }, expect: () => passes },
    "./personas": {
      decodeDotenvQuotedValue: (value) => value,
      gotoOnion: async () => undefined,
      normalizeBaseUrl: (value) => value,
    },
    "./service-gating": { isServiceEnabled: () => false },
    "./timeouts": { isSplitRealmOidc: () => false, resolveTimeout: (ms) => ms },
  },
  {},
);

test("the login-error view types a wrong password drawn from node:crypto", async () => {
  const filled = {};
  const locator = (selector) => ({
    click: async () => undefined,
    fill: async (value) => {
      filled[selector] = value;
    },
    first: () => locator(selector),
  });
  const page = {
    context: () => ({ clearCookies: async () => undefined }),
    locator,
    waitForLoadState: async () => undefined,
  };
  await galleryViews()
    .find((view) => view.name === "login-error")
    .prepare(page);
  assert.equal(filled[PASSWORD], `wrong-${CSPRNG_UUID}`);
});
