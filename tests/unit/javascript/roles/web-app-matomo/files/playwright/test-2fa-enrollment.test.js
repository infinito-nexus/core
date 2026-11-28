const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-matomo/files/playwright/test-2fa-enrollment.js");
const MENU = "#secondNavBar";
const SETUP_HTML =
  '<div vue-entry="TwoFactorAuth.SetupTwoFactorAuth" new-secret="&quot;JBSWY3DPEHPK3PXP&quot;" auth-code-nonce="&quot;nonce1&quot;"></div>';
const REPORTS_HTML = '<div id="secondNavBar"></div>';

/**
 * Args:
 *   events: the list every call is recorded in.
 *
 * Returns:
 *   An `expect` double whose matchers, negated or not, record the selector and message they assert.
 */
function recordingExpect(events) {
  return (target, message) => {
    const matchers = new Proxy(
      {},
      {
        get: (_, name) =>
          name === "not" ? matchers : () => events.push(["expect", String(name), target?.selector, message]),
      },
    );
    return matchers;
  };
}

/**
 * Args:
 *   enforced: the LOGIN_METHOD_2FA_ENFORCED flag the spec reads.
 *
 * Returns:
 *   The spec's registered tests by name, the recorded events and the page double they run against.
 */
function loadSpec(enforced) {
  const events = [];
  const registered = new Map();
  const playwrightTest = (name, body) => registered.set(name, body);
  playwrightTest.skip = (condition) => {
    if (condition) throw new Error("skipped");
  };
  playwrightTest.setTimeout = () => {};

  let reportsHtml = enforced ? SETUP_HTML : REPORTS_HTML;
  const page = {
    locator: (selector) => ({
      selector,
      first() {
        return this;
      },
    }),
    request: {
      post: async () => {
        events.push(["confirm"]);
        reportsHtml = REPORTS_HTML;
        return { status: () => 200 };
      },
    },
  };

  loadInternals(
    SPEC,
    [],
    {
      "node:crypto": crypto,
      "@playwright/test": { test: playwrightTest, expect: recordingExpect(events) },
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./totp": { totpCode: () => "123456" },
      "./personas": {
        gotoOnion: async () => {
          events.push(["reports"]);
          return { text: async () => reportsHtml };
        },
      },
      "./_shared": {
        adminPassword: "secret",
        adminUsername: "administrator",
        appBaseUrl: "https://matomo.example.org",
        canonicalDomain: "example.org",
        matomoApi: async (request, method) => {
          events.push(["api", method]);
          return { result: "success" };
        },
        nativeLoginEnabled: true,
        seedVisits: async () => events.push(["seed"]),
        signIn: async () => events.push(["signIn"]),
        twoFactorEnforced: enforced,
      },
    },
    { URL, console },
  );
  return { events, page, registered };
}

/**
 * Args:
 *   enforced: the LOGIN_METHOD_2FA_ENFORCED flag the spec reads.
 *   prefix: the start of the test name to run.
 *
 * Returns:
 *   The events the named test recorded.
 */
async function run(enforced, prefix) {
  const { events, page, registered } = loadSpec(enforced);
  const [, body] = [...registered].find(([name]) => name.startsWith(prefix));
  await body({ page, request: {} });
  return events;
}

function menuShown(events) {
  return events.findIndex(([kind, matcher, selector]) => kind === "expect" && matcher === "toBeVisible" && selector === MENU);
}

test("the enforced enrollment seeds site 1 before it asserts the reporting menu", async () => {
  const events = await run(true, "2fa enrollment: with its own second factor enforced");

  const seeded = events.findIndex(([kind]) => kind === "seed");
  assert.ok(menuShown(events) > 0, "the spec must assert the reporting menu once enrolled");
  assert.ok(seeded >= 0 && seeded < menuShown(events), "site 1 must hold a visit before the reporting menu is asserted");
});

test("the unenforced sign-in seeds site 1 before it asserts the reporting menu", async () => {
  const events = await run(false, "2fa enrollment: with the enforcement off");

  const seeded = events.findIndex(([kind]) => kind === "seed");
  assert.ok(menuShown(events) > 0, "the spec must assert the reporting menu");
  assert.ok(seeded >= 0 && seeded < menuShown(events), "site 1 must hold a visit before the reporting menu is asserted");
});

test("the administrator, kept on the setup and away from the menu, needs no seeded site", async () => {
  const events = await run(true, "2fa enrollment: the enforced second factor sends the Matomo administrator");

  assert.equal(menuShown(events), -1);
  assert.equal(
    events.some(([kind]) => kind === "seed"),
    false,
  );
});
