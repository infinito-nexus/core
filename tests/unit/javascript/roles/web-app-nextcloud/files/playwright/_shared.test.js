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
const SHELL_URL = `${CLEARNET}apps/dashboard/`;
const KEYCLOAK_LOGOUT_URL = "https://auth.example.org/realms/main/protocol/openid-connect/logout";

/**
 * Load _shared.js against the real gating helpers and the given env.
 *
 * Args:
 *   env: the Playwright env keys the flavor and the base URL are read from.
 *   pageHelpers: stand-ins for the exports of ./_page.
 *   expect: stand-in for the expect of @playwright/test.
 *   personas: stand-ins for the exports of ./personas beside decodeDotenvQuotedValue.
 */
function loadShared(env, pageHelpers = {}, expect = () => undefined, personas = {}) {
  for (const key of FLAVOR_ENV) delete process.env[key];
  Object.assign(process.env, env);
  const playwright = { "@playwright/test": { expect, test: { skip: () => undefined } } };
  const { isAddonEnabled } = loadInternals(path.join(GATING, "addon-gating.js"), ["isAddonEnabled"], playwright, {});
  const { isServiceEnabled } = loadInternals(path.join(GATING, "service-gating.js"), ["isServiceEnabled"], playwright, {});
  return loadInternals(
    SHARED,
    ["nextcloudLoginFlavor", "attemptStandaloneNextcloudLogin", "logoutStandaloneNextcloud"],
    {
      ...playwright,
      "./timeouts": { resolveTimeout: (ms) => ms },
      "./personas": { decodeDotenvQuotedValue: (value) => value, ...personas },
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

/**
 * Args:
 *   landing: the URL the Log out click commits, or null when the click does not navigate.
 *
 * Returns:
 *   the URLs the page showed whenever the shared Keycloak confirmation helper ran, and the
 *   error the logout raised, if any.
 */
async function logOutFromShell(landing) {
  let current = SHELL_URL;
  const confirmedOn = [];
  const logoutLink = {
    click: async () => {
      if (landing) current = landing;
    },
  };
  const stockLabelButton = {
    waitFor: async () => {
      throw new Error("no button named Logout on the corporate confirmation page");
    },
    click: async () => undefined,
  };
  const page = {
    url: () => current,
    locator: () => ({ first: () => ({}) }),
    getByRole: () => ({ first: () => stockLabelButton, click: async () => undefined }),
    waitForURL: async (predicate) => {
      if (!predicate(new URL(current))) throw new Error("TimeoutError: page.waitForURL");
    },
    waitForLoadState: async () => undefined,
  };
  const { logoutStandaloneNextcloud } = loadShared(
    { SSO_SERVICE_ENABLED: "true", LDAP_SERVICE_ENABLED: "true", USER_OIDC_ADDON_ENABLED: "false", NEXTCLOUD_BASE_URL: CLEARNET },
    {
      dismissBlockingNextcloudModals: async () => undefined,
      clickWithModalRetry: async () => undefined,
      waitForFirstVisible: async () => logoutLink,
    },
    () => ({ toBeVisible: async () => undefined }),
    {
      confirmKeycloakLogoutIfPrompted: async (target) => {
        confirmedOn.push(target.url());
      },
    },
  );
  const error = await logoutStandaloneNextcloud(page).then(
    () => null,
    (raised) => raised,
  );
  return { confirmedOn, error };
}

test("a Log out the universal logout sends to the Keycloak confirmation page is confirmed there", async () => {
  const { confirmedOn, error } = await logOutFromShell(KEYCLOAK_LOGOUT_URL);

  assert.equal(error, null);
  assert.deepEqual(
    confirmedOn,
    [KEYCLOAK_LOGOUT_URL],
    "the shared helper submits #kc-logout whatever label the realm theme gives it, so the Keycloak session ends",
  );
});

test("a Log out click that never leaves the shell fails instead of passing as a logout", async () => {
  const { confirmedOn, error } = await logOutFromShell(null);

  assert.match(String(error), /waitForURL/);
  assert.deepEqual(confirmedOn, [], "nothing is confirmed while the signed-in shell is still shown");
});
