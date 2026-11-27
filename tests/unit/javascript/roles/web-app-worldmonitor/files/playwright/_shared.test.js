const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const NO_OP_MATCHERS = new Proxy({}, { get: () => async () => undefined });
const identity = (value) => value;

/**
 * Args:
 *   events: list every navigation, confirmation click and load wait is appended to.
 *
 * Returns:
 *   The `logout` and `leaveDashboard` functions of the role's shared module.
 */
function loadShared(events) {
  return loadInternals(
    path.join(PROJECT_ROOT, "roles/web-app-worldmonitor/files/playwright/_shared.js"),
    ["logout", "leaveDashboard"],
    {
      "@playwright/test": { expect: () => NO_OP_MATCHERS },
      "./timeouts": { resolveTimeout: identity },
      "./personas": {
        decodeDotenvQuotedValue: identity,
        normalizeBaseUrl: identity,
        gotoOnion: async (_page, url) => events.push(`goto ${url}`),
        safeIsEnabled: () => true,
        assertCspInjections: async () => undefined,
      },
    },
    {},
  );
}

function fakePage(events) {
  return {
    locator: () => ({ waitFor: async () => undefined, click: async () => events.push("confirm") }),
    waitForLoadState: async () => events.push("loaded"),
  };
}

test("leaving the dashboard parks the tab on a blank page", async () => {
  const events = [];
  const { leaveDashboard } = loadShared(events);
  await leaveDashboard(fakePage(events));
  assert.deepEqual(events, ["goto about:blank"]);
});

test("logout leaves the live dashboard before the sign-out ends its gate session", async () => {
  const events = [];
  const { logout } = loadShared(events);
  await logout(fakePage(events));
  assert.equal(events[0], "goto about:blank");
  assert.match(events[1], /^goto \S*\/oauth2\/sign_out\?rd=/);
  assert.deepEqual(events.slice(2, 4), ["confirm", "loaded"]);
});
