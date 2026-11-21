const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));
const FILES = path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files");
const network = require(path.join(FILES, "personas/utils/network.js"));

const NODE = "b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion";
const ONION_RUN = { APP_BASE_URL: `"http://cosmos.${NODE}/"`, OIDC_ISSUER_URL: `"https://auth.${DOMAIN}/realms/x"` };
const CLEARNET_RUN = { APP_BASE_URL: `"https://cosmos.${DOMAIN}/"`, OIDC_ISSUER_URL: `"https://auth.${DOMAIN}/realms/x"` };
const HARNESS = {
  PLAYWRIGHT_NETWORK_SUFFIXES: JSON.stringify({ tor: ".onion" }),
  PLAYWRIGHT_TEST_TIMEOUT: "1000",
  PLAYWRIGHT_EXPECT_TIMEOUT: "1000",
  PLAYWRIGHT_NAVIGATION_TIMEOUT: "1000",
  PLAYWRIGHT_ACTION_TIMEOUT: "1000",
};

/**
 * Args:
 *   file: the harness file to evaluate, relative to the role's files directory.
 *   modules: module per `require` request the file makes.
 *   env: the variables the staged .env of the run hands in.
 *
 * Returns:
 *   What the file exports when it is evaluated under that environment.
 */
function loadUnder(file, modules, env) {
  const saved = { ...process.env };
  Object.assign(process.env, HARNESS, env);
  try {
    const globals = {};
    loadInternals(path.join(FILES, file), [], modules, globals);
    return globals.module.exports;
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in saved)) delete process.env[key];
    }
    Object.assign(process.env, saved);
  }
}

/**
 * Args:
 *   env: the variables the staged .env of the run hands in.
 *
 * Returns:
 *   The `use` block playwright.config.js hands every worker.
 */
function useBlock(env) {
  const config = loadUnder(
    "playwright.config.js",
    {
      "@playwright/test": { defineConfig: (definition) => definition },
      "./tests/personas/utils/network": network,
    },
    env,
  );
  return structuredClone(config.use);
}

test("an onion run launches the full Chromium with the onion origins treated as secure", () => {
  const use = useBlock(ONION_RUN);
  assert.equal(use.channel, "chromium");
  assert.deepEqual(use.launchOptions, {
    args: [`--unsafely-treat-insecure-origin-as-secure=http://cosmos.${NODE}`],
  });
});

test("a clearnet run keeps the default headless shell and passes no flag", () => {
  const use = useBlock(CLEARNET_RUN);
  assert.equal("channel" in use, false);
  assert.equal("launchOptions" in use, false);
});

test("the onion Firefox fixture drops the Chromium channel every launch inherits", async () => {
  const { test: onionTest } = loadUnder(
    "onion-test.js",
    {
      "@playwright/test": { test: { extend: (fixtures) => fixtures } },
      "./personas/utils/network": network,
    },
    ONION_RUN,
  );
  const launched = [];
  const playwright = {
    firefox: {
      launch: async (options) => {
        launched.push(options);
        return { close: async () => {} };
      },
    },
  };
  await onionTest.browser({ playwright }, async () => {});

  const inherited = { ...useBlock(ONION_RUN).launchOptions, channel: "chromium" };
  assert.equal(launched.length, 1);
  assert.equal({ ...inherited, ...launched[0] }.channel, undefined);
});
