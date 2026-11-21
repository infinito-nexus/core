const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { loadInternals } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/internals.js"));

const SHARED = path.join(PROJECT_ROOT, "roles/web-app-nextcloud/files/playwright/_shared.js");
const GATING = path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files");
const CLEARNET = "https://next.example.org/";
const ONION = `http://next.${"a".repeat(56)}.onion/`;
const FLAVOR_ENV = ["SSO_SERVICE_ENABLED", "LDAP_SERVICE_ENABLED", "USER_OIDC_ADDON_ENABLED", "NEXTCLOUD_BASE_URL"];

/**
 * Load _shared.js against the real gating helpers and the given env.
 *
 * Args:
 *   env: the Playwright env keys the flavor and the base URL are read from.
 *   pageHelpers: stand-ins for the exports of ./_page.
 *   expect: stand-in for the expect of @playwright/test.
 */
function loadShared(env, pageHelpers = {}, expect = () => undefined) {
  for (const key of FLAVOR_ENV) delete process.env[key];
  Object.assign(process.env, env);
  const playwright = { "@playwright/test": { expect, test: { skip: () => undefined } } };
  const { isAddonEnabled } = loadInternals(path.join(GATING, "addon-gating.js"), ["isAddonEnabled"], playwright, {});
  const { isServiceEnabled } = loadInternals(path.join(GATING, "service-gating.js"), ["isServiceEnabled"], playwright, {});
  return loadInternals(
    SHARED,
    ["nextcloudLoginFlavor", "attemptStandaloneNextcloudLogin"],
    {
      ...playwright,
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": { decodeDotenvQuotedValue: (value) => value },
      "./addon-gating": { isAddonEnabled },
      "./service-gating": { isServiceEnabled },
      "./_page": pageHelpers,
    },
    { URL },
  );
}

function flavor(env) {
  return loadShared({ NEXTCLOUD_BASE_URL: CLEARNET, ...env }).nextcloudLoginFlavor;
}

test("the user_oidc addon selects the user_oidc flavor, also beside LDAP", () => {
  assert.equal(
    flavor({ SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "true", USER_OIDC_ADDON_ENABLED: "true" }),
    "user_oidc",
  );
  assert.equal(
    flavor({ SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "false", USER_OIDC_ADDON_ENABLED: "true" }),
    "user_oidc",
  );
});

test("without the user_oidc addon the flavor stays the one LDAP picks", () => {
  assert.equal(
    flavor({ SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "true", USER_OIDC_ADDON_ENABLED: "false" }),
    "oidc_login",
  );
  assert.equal(
    flavor({ SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "false", USER_OIDC_ADDON_ENABLED: "false" }),
    "sociallogin",
  );
});

test("with SSO off the native form wins over a stale user_oidc flag", () => {
  assert.equal(
    flavor({ SSO_SERVICE_ENABLED: "false", LDAP_SERVICE_ENABLED: "true", USER_OIDC_ADDON_ENABLED: "true" }),
    "native",
  );
});

test("a user_oidc sign-in on another network opens that network's login page and stops at a shell Keycloak already signed in", async () => {
  const visited = [];
  const credentialForm = { touched: false };
  const handovers = [
    { kind: "social-login", locator: { click: async () => undefined } },
    { kind: "shell", locator: {} },
  ];
  const locator = { first: () => locator, click: async () => undefined, fill: async () => undefined, press: async () => undefined };
  const page = {
    goto: async (url) => {
      visited.push(url);
    },
    getByRole: () => locator,
    locator: () => locator,
  };
  const expect = () => ({
    toBeVisible: async () => {
      credentialForm.touched = true;
    },
  });
  const { attemptStandaloneNextcloudLogin } = loadShared(
    { SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "true", USER_OIDC_ADDON_ENABLED: "true", NEXTCLOUD_BASE_URL: CLEARNET },
    {
      getNextcloudShellCandidates: () => [],
      trackServerErrors: () => undefined,
      waitForVisibleCandidate: async () => handovers.shift() ?? { kind: "shell", locator: {} },
      dismissBlockingNextcloudModals: async () => undefined,
    },
    expect,
  );

  await attemptStandaloneNextcloudLogin(page, "biber", "secret", ONION);

  assert.deepEqual(visited, [`${ONION}login`]);
  assert.equal(handovers.length, 0, "both the entry and the handover were awaited");
  assert.equal(credentialForm.touched, false, "an existing Keycloak session leaves no credential form to fill");
});
