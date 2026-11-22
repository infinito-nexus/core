const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));
const UTILS = path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils");
const network = require(path.join(UTILS, "network.js"));
const dotenv = require(path.join(UTILS, "dotenv.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-svc-xmpp/files/playwright/playwright.spec.js");
const ONION = `xmpp.${"a".repeat(56)}.onion`;
const BASE_URL = `http://${ONION}`;
const BASELINE = "baseline: ejabberd HTTP API responds on the canonical domain";
const LDAP_GUEST = "guest: ejabberd LDAP backend points at svc-db-openldap (variant 1)";
const EJABBERD_CHALLENGE = 'basic realm="ejabberd"';

Object.assign(process.env, {
  PLAYWRIGHT_NETWORK_SUFFIXES: JSON.stringify({ tor: ".onion" }),
  XMPP_BASE_URL: `"${BASE_URL}/"`,
  CANONICAL_DOMAIN: `"${ONION}"`,
});

/**
 * Args:
 *   file: absolute path of the CommonJS file to evaluate.
 *   modules: module per `require` request the file makes.
 *
 * Returns:
 *   What the file exports.
 */
function load(file, modules) {
  const globals = {};
  loadInternals(file, [], modules, globals);
  return globals.module.exports;
}

const onion = load(path.join(UTILS, "onion.js"), {
  "../../timeouts": { isOnionTarget: () => true, resolveTimeout: (ms) => ms },
  "./csp": { installCspHeaderRecorder: () => {} },
  "./network": network,
});

/**
 * Args:
 *   actual: the value under assertion.
 *
 * Returns:
 *   The matchers the spec calls on it.
 */
function expect(actual) {
  return {
    toBe: (expected) => assert.equal(actual, expected),
    toBeLessThan: (bound) => assert.ok(actual < bound, `${actual} is not below ${bound}`),
    toMatch: (pattern) => assert.match(actual, pattern),
  };
}

/**
 * Returns:
 *   The body of every test the spec registers, keyed by its title.
 */
function specBodies() {
  const bodies = {};
  const register = Object.assign((title, body) => {
    bodies[title] = body;
  }, { use: () => {}, beforeEach: () => {} });
  load(SPEC, {
    "@playwright/test": { test: register, expect },
    "./service-gating": { skipUnlessServiceEnabled: () => {} },
    "./personas": { ...dotenv, ...onion },
    "./timeouts": { resolveTimeout: (ms) => ms },
  });
  return bodies;
}

/**
 * Args:
 *   status: the status /admin answers an anonymous request with.
 *   challenge: its WWW-Authenticate header, undefined for none.
 *
 * Returns:
 *   A page whose navigation onto a 401 fails the way the full Chromium of onion runs does,
 *   and the requests its HTTP client sent.
 */
function fullChromiumPage(status, challenge) {
  const sent = [];
  const headers = challenge === undefined ? {} : { "www-authenticate": challenge };
  const response = (url) => ({ status: () => status, url: () => url, headers: () => headers });
  const page = {
    goto: async (url) => {
      if (status === 401) throw new Error(`page.goto: net::ERR_INVALID_AUTH_CREDENTIALS at ${url}`);
      return response(url);
    },
    request: {
      fetch: async (url, options) => {
        sent.push({ url, method: options.method });
        return response(url);
      },
    },
  };
  return { page, sent };
}

const spec = specBodies();

test("the baseline accepts ejabberd's Basic challenge on the full Chromium of onion runs", async () => {
  const { page, sent } = fullChromiumPage(401, EJABBERD_CHALLENGE);
  await spec[BASELINE]({ page });
  assert.deepEqual(sent, [{ url: `${BASE_URL}/admin/`, method: "GET" }]);
});

test("the LDAP guest probe accepts the same challenge", async () => {
  const { page, sent } = fullChromiumPage(401, EJABBERD_CHALLENGE);
  await spec[LDAP_GUEST]({ page });
  assert.deepEqual(sent, [{ url: `${BASE_URL}/admin/`, method: "GET" }]);
});

test("the baseline fails when ejabberd is not the one answering /admin", async () => {
  for (const [status, challenge] of [
    [404, undefined],
    [401, 'Basic realm="openresty"'],
    [502, undefined],
  ]) {
    const { page } = fullChromiumPage(status, challenge);
    await assert.rejects(async () => spec[BASELINE]({ page }), `status ${status} must fail the baseline`);
  }
});
