const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));
const network = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/network.js"));
const dotenv = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dotenv.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-mini-qr/files/playwright/test-design.js");
const TOR = { tor: ".onion" };
const ONION = `http://qr.${"a".repeat(56)}.onion`;

const { targetNetwork } = loadInternals(
  SPEC,
  ["targetNetwork"],
  {
    "./personas": dotenv,
    "./personas/utils/network": network,
  },
  { Buffer, URL },
);

/**
 * Args:
 *   baseUrl: the APP_BASE_URL the spec runs against.
 *   suffixes: the PLAYWRIGHT_NETWORK_SUFFIXES the run hands in, undefined for none.
 *
 * Returns:
 *   The network the streaming scanner test skips on unless it is clearnet.
 */
function networkFor(baseUrl, suffixes) {
  process.env.APP_BASE_URL = baseUrl;
  delete process.env.PLAYWRIGHT_NETWORK_SUFFIXES;
  if (suffixes !== undefined) process.env.PLAYWRIGHT_NETWORK_SUFFIXES = JSON.stringify(suffixes);
  return targetNetwork();
}

test("a mini-qr on the onion network is outside clearnet, so the camera browser skips it", () => {
  assert.equal(networkFor(`${ONION}/`, TOR), "tor");
  assert.equal(networkFor(`${ONION}:8080/qr/`, TOR), "tor");
});

test("a clearnet mini-qr keeps the streaming scanner test", () => {
  assert.equal(networkFor(`https://qr.${DOMAIN}/`, TOR), "clearnet");
  assert.equal(networkFor(`https://qr.${DOMAIN}/`, {}), "clearnet");
});

test("the network registry the run hands in decides, not a suffix of its own", () => {
  assert.equal(networkFor("http://qr.example.i2p/", { i2p: ".i2p" }), "i2p");
  assert.equal(networkFor(`${ONION}/`, {}), "clearnet");
});

test("a pass without the network registry fails instead of guessing clearnet", () => {
  assert.throws(() => networkFor(`https://qr.${DOMAIN}/`, undefined), /PLAYWRIGHT_NETWORK_SUFFIXES is empty/);
  assert.throws(() => networkFor(`${ONION}/`, undefined), /PLAYWRIGHT_NETWORK_SUFFIXES is empty/);
});
