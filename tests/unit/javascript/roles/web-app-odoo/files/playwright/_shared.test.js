const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));
const network = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/network.js"));
const dotenv = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-odoo/files/playwright/_shared.js");
const TOR = { tor: ".onion" };
const ONION = `http://odoo.${"a".repeat(56)}.onion`;
const PROXIED = { serviceWorkers: "block" };

/**
 * Args:
 *   baseUrl: the ODOO_BASE_URL the specs run against.
 *   suffixes: the PLAYWRIGHT_NETWORK_SUFFIXES the run hands in, undefined for none.
 *
 * Returns:
 *   The browser options _shared.js hands every Odoo spec.
 */
function onionOptionsFor(baseUrl, suffixes) {
  process.env.ODOO_BASE_URL = baseUrl;
  delete process.env.PLAYWRIGHT_NETWORK_SUFFIXES;
  if (suffixes !== undefined) process.env.PLAYWRIGHT_NETWORK_SUFFIXES = JSON.stringify(suffixes);
  const { onionOptions } = loadInternals(
    SHARED,
    ["onionOptions"],
    {
      "./personas": dotenv,
      "./personas/utils/network": network,
    },
    { URL },
  );
  return { ...onionOptions };
}

test("an Odoo on the onion network runs without service workers", () => {
  assert.deepEqual(onionOptionsFor(ONION, TOR), PROXIED);
  assert.deepEqual(onionOptionsFor(`${ONION}/web/login`, TOR), PROXIED);
});

test("a clearnet Odoo keeps the default browser", () => {
  assert.deepEqual(onionOptionsFor(`https://odoo.${DOMAIN}`, TOR), {});
  assert.deepEqual(onionOptionsFor(`https://odoo.${DOMAIN}`, {}), {});
});

test("the network registry the run hands in decides, not a suffix of its own", () => {
  assert.deepEqual(onionOptionsFor("http://odoo.example.i2p", { i2p: ".i2p" }), PROXIED);
  assert.deepEqual(onionOptionsFor(ONION, {}), {});
});

test("a pass without the network registry fails instead of guessing clearnet", () => {
  assert.throws(() => onionOptionsFor(`https://odoo.${DOMAIN}`, undefined), /PLAYWRIGHT_NETWORK_SUFFIXES is empty/);
  assert.throws(() => onionOptionsFor(ONION, undefined), /PLAYWRIGHT_NETWORK_SUFFIXES is empty/);
});
