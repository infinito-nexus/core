const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const SPEC = path.join(PROJECT_ROOT, "roles/web-app-shopware/files/playwright/test-design.js");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const dotenv = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));

const ENV = {
  APP_BASE_URL: '"https://shop.example"',
  SHOWCASE_PRODUCT_ID: '"d0000000000000000000000000000011"',
  SHOWCASE_PRODUCT_NAME: '"Design showcase lamp"',
  SHOWCASE_CUSTOMER_EMAIL: '"design-showcase@shop.example"',
  SHOWCASE_CUSTOMER_PASSWORD: '"seeded-at-deploy"',
  SHOWCASE_CHANNEL_ID: '"channel"',
  SHOWCASE_THEME_ID: '"theme"',
  SHOWCASE_THEME_CONFIG: '"{\\"sw-color-brand-primary\\":\\"#123456\\"}"',
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

Object.assign(process.env, ENV);
const { showcase, signInCustomer } = loadInternals(
  SPEC,
  ["showcase", "signInCustomer"],
  {
    "@playwright/test": { test: () => undefined, expect: () => passes },
    "./personas": { ...dotenv, gotoOnion: async () => undefined },
    "./timeouts": { resolveTimeout: (ms) => ms },
  },
  {},
);

test("the showcase customer signs in with the email and password the deploy seeded and handed over in .env", async () => {
  const filled = {};
  const locator = (selector) => ({
    fill: async (value) => {
      filled[selector] = value;
    },
    locator,
    press: async () => undefined,
  });
  await signInCustomer({ locator });

  assert.equal(filled["input[name='username']"], "design-showcase@shop.example");
  assert.equal(filled["input[name='password']"], "seeded-at-deploy");
});

test("the channel, theme and theme configuration come from the deploy's seed output", () => {
  const seeded = showcase();

  assert.equal(seeded.productId, "d0000000000000000000000000000011");
  assert.equal(seeded.channelId, "channel");
  assert.equal(seeded.themeId, "theme");
  assert.deepEqual(seeded.themeConfig, { "sw-color-brand-primary": "#123456" });
});

test("negative control: a run whose .env carries no seeded password fails instead of signing in with an empty one", () => {
  process.env.SHOWCASE_CUSTOMER_PASSWORD = '""';
  try {
    assert.throws(showcase, /SHOWCASE_CUSTOMER_PASSWORD is empty/);
  } finally {
    process.env.SHOWCASE_CUSTOMER_PASSWORD = ENV.SHOWCASE_CUSTOMER_PASSWORD;
  }
});

test("the spec reads no key: no mounted secret, no token grant, no admin API call and no random password", () => {
  const source = fs.readFileSync(SPEC, "utf8");

  for (const forbidden of ["/run/spec-secrets", "oauth/token", "/api/_action/sync", "/api/search/", "node:crypto", "node:fs", "INTEGRATION"]) {
    assert.ok(!source.includes(forbidden), `the design spec must not reference ${forbidden}`);
  }
});
