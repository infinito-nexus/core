const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const { cspPolicies, recordAuthorizationHops } = loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-worldmonitor/files/playwright/test-oidc-login.js"),
  ["cspPolicies", "recordAuthorizationHops"],
  {},
  {},
);
const POLICY = "default-src 'self'; script-src 'self' 'sha256-abc='";
const KEYCLOAK_AUTH_RE = /openid-connect\/auth/;
const SSO_REUSE_SCENARIO = "biber: an existing Keycloak session reaches the dashboard without an interactive login";
const scenarios = {};
const scenarioContext = {};
const sharedSteps = [];
const shared = {
  env: { biberUsername: "biber", biberPassword: "secret" },
  KEYCLOAK_AUTH_RE,
  loginToDashboard: async () => sharedSteps.push("login"),
  leaveDashboard: async () => sharedSteps.push("leave"),
  openApp: async (_page, appPath) => sharedSteps.push(`open ${appPath}`),
  expectDashboard: async () => sharedSteps.push("dashboard"),
  logout: async () => sharedSteps.push("logout"),
};
function registerScenario(name, body) {
  scenarios[name] = body;
}
registerScenario.setTimeout = () => undefined;
loadInternals(
  path.join(PROJECT_ROOT, "roles/web-app-worldmonitor/files/playwright/test-oidc-login.js"),
  [],
  { "@playwright/test": { test: registerScenario, expect: () => new Proxy({}, { get: () => () => undefined }) } },
  scenarioContext,
);
scenarioContext.module.exports.register(shared);
const AUTHORIZE = "https://auth.example.org/realms/main/protocol/openid-connect/auth?client_id=wm";

function fakePage() {
  const handlers = {};
  return {
    on: (event, handler) => {
      handlers[event] = handler;
    },
    respond: (url, status, navigation) =>
      handlers.response({ url: () => url, status: () => status, request: () => ({ isNavigationRequest: () => navigation }) }),
  };
}

test("one Content-Security-Policy header is one policy, the report-only header does not count", () => {
  assert.deepEqual(
    cspPolicies([
      { name: "Content-Security-Policy", value: POLICY },
      { name: "content-security-policy-report-only", value: "default-src 'none'" },
      { name: "Content-Type", value: "text/html" },
    ]),
    [POLICY],
  );
});

test("a second header, a joined duplicate and a comma-separated list are all a second policy", () => {
  const upstream = "default-src 'self'; frame-ancestors *";
  assert.equal(
    cspPolicies([
      { name: "content-security-policy", value: POLICY },
      { name: "content-security-policy", value: upstream },
    ]).length,
    2,
  );
  assert.equal(cspPolicies([{ name: "content-security-policy", value: `${POLICY}\n${upstream}` }]).length, 2);
  assert.equal(cspPolicies([{ name: "content-security-policy", value: `${POLICY}, ${upstream}` }]).length, 2);
});

test("no Content-Security-Policy header is no policy", () => {
  assert.deepEqual(cspPolicies([{ name: "Content-Type", value: "text/html" }]), []);
});

test("only navigations to the authorization endpoint count as hops, with their status", () => {
  const page = fakePage();
  const hops = recordAuthorizationHops(page, KEYCLOAK_AUTH_RE);
  page.respond("https://wm.example.org/", 302, true);
  page.respond(AUTHORIZE, 302, true);
  page.respond(`${AUTHORIZE}&prompt=none`, 200, false);
  page.respond("https://wm.example.org/oauth2/callback?code=c", 302, true);
  page.respond(AUTHORIZE, 200, true);
  assert.deepEqual([...hops], [302, 200]);
});

test("the SSO reuse scenario leaves the live dashboard before it drops the gate session", async () => {
  sharedSteps.length = 0;
  const page = {
    on: () => undefined,
    context: () => ({ clearCookies: async () => sharedSteps.push("drop gate session") }),
  };
  await scenarios[SSO_REUSE_SCENARIO]({ page });
  assert.deepEqual(sharedSteps.slice(0, 4), ["login", "leave", "drop gate session", "open /"]);
});
