const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const noop = () => undefined;
const { isSiteSweep } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-joomla/files/playwright/test-sso-logout.js"),
  ["isSiteSweep"],
  { "@playwright/test": { test: Object.assign(noop, { use: noop }), expect: noop } },
  { URL },
);

const SITE = "http://joomla.cms.example.onion";
const response = (url) => ({ url: () => url });

test("the conductor's cache-busted /logout call on the Joomla origin is the sweep the spec waits for", () => {
  assert.equal(isSiteSweep(SITE)(response(`${SITE}/logout?t=abc123`)), true);
});

test("the logout service's own /logout and another application's /logout are not the Joomla sweep", () => {
  const sweep = isSiteSweep(SITE);
  assert.equal(sweep(response("http://logout.example.onion/logout?t=abc123")), false);
  assert.equal(sweep(response("http://matomo.example.onion/logout?t=abc123")), false);
});

test("the Joomla front page, its own logout task and the Keycloak end-session endpoint are not the sweep", () => {
  const sweep = isSiteSweep(SITE);
  assert.equal(sweep(response(`${SITE}/`)), false);
  assert.equal(sweep(response(`${SITE}/index.php?option=keycloak&task=logout`)), false);
  assert.equal(sweep(response(`${SITE}/logout/extra`)), false);
  assert.equal(sweep(response("http://auth.example.onion/realms/main/protocol/openid-connect/logout")), false);
});
