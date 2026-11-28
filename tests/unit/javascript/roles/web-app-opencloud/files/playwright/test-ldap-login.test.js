const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SPEC = path.join(PROJECT_ROOT, "roles/web-app-opencloud/files/playwright/test-ldap-login.js");
const SIGN_IN_FORM = "visible #oc-login-username";

const noop = () => undefined;
const scenarios = [];
let events = [];

function locator(selector) {
  return {
    selector,
    fill: async () => events.push(`fill ${selector}`),
    press: async () => events.push(`press ${selector}`),
  };
}

function expectation(value) {
  return {
    toBeVisible: async () => events.push(`visible ${value && value.selector}`),
    toBeTruthy: noop,
    toBeUndefined: noop,
    toBe: noop,
  };
}

const page = {
  addInitScript: async () => undefined,
  locator,
  getByRole: (role) => locator(`role=${role}`),
  evaluate: async () => ({ account: {} }),
};

loadInternals(
  SPEC,
  [],
  {
    "./onion-test": {
      test: Object.assign((title, body) => scenarios.push({ title, body }), { use: noop }),
      expect: expectation,
    },
    "./timeouts": { resolveTimeout: (ms) => ms },
    "./personas": { gotoOnion: async (_page, url) => events.push(`goto ${url}`) },
    "./service-gating": { skipUnlessServiceDisabled: noop, skipUnlessServiceEnabled: noop },
    "./_shared": {
      adminPassword: "administrator-password",
      adminUsername: "administrator",
      baseUrl: "https://opencloud.example.test/",
      biberPassword: "biber-password",
      biberUsername: "biber",
      logoutThroughAccountMenu: async () => events.push("logout"),
    },
  },
  {},
);

test("the spec registers one built-in sign-in scenario per persona", () => {
  assert.equal(scenarios.length, 2);
});

for (const scenario of scenarios) {
  test(`${scenario.title}: the sign-out lands on the sign-in form before the protected request`, async () => {
    events = [];
    await scenario.body({ page });

    const logout = events.indexOf("logout");
    assert.notEqual(logout, -1, "the scenario must sign out through the account menu");
    const afterLogout = events.slice(logout + 1);
    const protectedRequest = afterLogout.findIndex((event) => event.startsWith("goto "));
    assert.notEqual(protectedRequest, -1, "after sign-out the scenario must still request a protected page");
    assert.ok(
      afterLogout.slice(0, protectedRequest).includes(SIGN_IN_FORM),
      "the signed-out SPA redirects to the identity provider on its own, and a navigation issued before that redirect lands is aborted with net::ERR_ABORTED",
    );
    assert.ok(
      afterLogout.slice(protectedRequest + 1).includes(SIGN_IN_FORM),
      "the protected request after sign-out must end on the sign-in form",
    );
  });
}
