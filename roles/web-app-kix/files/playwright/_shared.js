const { expect, request } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const {
  decodeDotenvQuotedValue,
  inAppLogout,
  performKeycloakLoginForm,
  requireDotenvValue,
  runBiberFlow,
  runGuestFlow,
  gotoOnion,
  withLdapGroupMember,
} = require("./personas");
const { isServiceEnabled, skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const keycloakAdmin = require("./personas/utils/keycloak");

const ssoEnabled    = isServiceEnabled("sso");

const appBaseUrl      = decodeDotenvQuotedValue(process.env.APP_BASE_URL      || "").replace(/\/$/, "");
const canonicalDomain = decodeDotenvQuotedValue(process.env.CANONICAL_DOMAIN  || "");
const oidcIssuerUrl   = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL   || "").replace(/\/$/, "");
const logoutUrl       = decodeDotenvQuotedValue(process.env.LOGOUT_URL        || "").replace(/\/$/, "");

const keycloak = {
  baseUrl:     decodeDotenvQuotedValue(process.env.KEYCLOAK_BASE_URL            || "").replace(/\/$/, ""),
  realm:       decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM               || ""),
  adminUser:   decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_USERNAME      || ""),
  adminPw:     decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_PASSWORD      || ""),
  adminRealm:  decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM         || ""),
  adminClient: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID || ""),
};
const kixUserGroupPath = requireDotenvValue(process.env.KIX_USER_GROUP_PATH, "KIX_USER_GROUP_PATH");
const biberUsername    = requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME");
const biberPassword    = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
const adminUsername    = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword    = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const biberDn          = requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN");
const userGroupDn      = requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN");

const KIX_SIGN_IN_PATH = "/auth";
const SETUP_STEP_LIMIT = 12;
const REROUTE_PATIENCE_MS = 10_000;
const BOOT_PATIENCE_MS = 20_000;
const HEADER = "#kix-header";
const CONTENT = ".content-wrapper";
const SETUP_STEPS = `${CONTENT} .setup-steps`;
const SETUP_STEP = `${SETUP_STEPS} .step`;
const SETUP_PENDING_STEP = `${SETUP_STEP}:not(.completed):not(.skipped)`;

function expectKeycloakAdminEnv() {
  for (const [key, value] of Object.entries({ ...keycloak, kixUserGroupPath, biberUsername, biberPassword })) {
    expect(value, `${key} must be set`).toBeTruthy();
  }
}

function keycloakAdminOpts() {
  return { adminRealm: keycloak.adminRealm, adminClientId: keycloak.adminClient };
}

async function withKeycloakAdmin(fn) {
  const api = await request.newContext({ ignoreHTTPSErrors: true });
  try {
    return await fn(api);
  } finally {
    await api.dispose().catch(() => {});
  }
}

async function withBiberInGroup(groupPath, fn) {
  let joined = false;
  try {
    joined = await withKeycloakAdmin((api) =>
      keycloakAdmin.keycloakAdminAddUserToGroup(
        api, keycloak.baseUrl, keycloak.realm, groupPath, biberUsername,
        keycloak.adminUser, keycloak.adminPw, keycloakAdminOpts(),
      ),
    );
    return await fn();
  } finally {
    if (joined) {
      await withKeycloakAdmin((api) =>
        keycloakAdmin.keycloakRemoveUserFromGroupViaRest(
          api, keycloak.baseUrl, keycloak.realm, keycloak.adminUser, keycloak.adminPw,
          groupPath, biberUsername, keycloakAdminOpts(),
        ),
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
  }
}

async function performKixLogin(page, username, password) {
  const usernameInput = page.locator('input[type="text"], input[type="email"], input[name="UserLogin"], input[name="username"]').first();
  const passwordInput = page.locator('input[type="password"]').first();
  const submitButton  = page.locator('button[type="submit"], input[type="submit"], button:has-text("Login")').first();

  await usernameInput.waitFor({ state: "visible", timeout: resolveTimeout(30_000) });
  await usernameInput.fill(username);
  await passwordInput.fill(password);
  await submitButton.click({ timeout: resolveTimeout(30_000) });
}

async function signInThroughGate(page, username, password) {
  const expectedAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected redirect to Keycloak OIDC auth: ${expectedAuthUrl}`,
    })
    .toContain(expectedAuthUrl);
  await performKeycloakLoginForm(page, username, password);
}

async function runKixLogin(page, username, password) {
  await signInThroughGate(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `Expected redirect back to canonical KIX URL on ${canonicalDomain}`,
    })
    .toContain(canonicalDomain);

  await page.waitForLoadState("domcontentloaded");
  await performKixLogin(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected SPA to leave /auth after successful LDAP login as ${username}`,
    })
    .not.toContain(KIX_SIGN_IN_PATH);
}

async function runKixLogout(page) {
  const expectedAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, logoutUrl, { waitUntil: "commit" }).catch(() => {});

  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected post-logout request to be re-gated to ${expectedAuthUrl}`,
    })
    .toContain(expectedAuthUrl);
}

async function runKixLoginLogoutFlow(page, username, password) {
  await runKixLogin(page, username, password);
  await runKixLogout(page);
}

async function runKixDirectoryLogin(page, username, password) {
  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await performKixLogin(page, username, password);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected SPA to leave /auth after the KIX-LDAP login as ${username}`,
    })
    .not.toContain(KIX_SIGN_IN_PATH);
}

async function expectKixSignIn(page, message) {
  await expect(page.locator('input[type="password"]').first(), message).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function runKixDirectoryLogout(page) {
  await inAppLogout(page);

  // KIX ends the session with a DELETE request after the click and only then navigates to its sign-in, which aborts
  // (net::ERR_ABORTED) any navigation started before that request returned.
  await expect
    .poll(() => new URL(page.url()).pathname, {
      timeout: resolveTimeout(60_000),
      message: "the in-app logout must end the KIX session and hand over to the KIX sign-in",
    })
    .toBe(KIX_SIGN_IN_PATH);
  await expectKixSignIn(page, "the in-app logout must land on the KIX sign-in");

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expectKixSignIn(page, "after the in-app logout a protected request must land on the KIX sign-in again");
}

async function runKixDirectoryLoginLogoutFlow(page, username, password) {
  await runKixDirectoryLogin(page, username, password);
  await runKixDirectoryLogout(page);
}

async function runKixLdapLoginLogoutFlow(page, username, password) {
  if (ssoEnabled) {
    await runKixLoginLogoutFlow(page, username, password);
  } else {
    await runKixDirectoryLoginLogoutFlow(page, username, password);
  }
}

async function withBiberInKixUserGroup(fn) {
  if (!ssoEnabled) {
    return withLdapGroupMember(userGroupDn, biberDn, fn);
  }
  expectKeycloakAdminEnv();
  return withBiberInGroup(kixUserGroupPath, fn);
}

/**
 * Args:
 *   page: Playwright page whose finite animations and transitions must have ended.
 */
async function animationsSettled(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          document
            .getAnimations()
            .some(
              (animation) =>
                animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity,
            ),
        ),
      { timeout: resolveTimeout(15_000), message: "every finite animation of the page must have ended" },
    )
    .toBe(false);
}

/**
 * A full load that routes into a context the app registers late, the administration among them, falls back to the
 * first open tab or Home, so a load that landed elsewhere is routed again inside the loaded app until the view shows,
 * through a popstate that carries a state because the app ignores one without. Chromium at times fails the large app
 * bundle out of its HTTP cache (net::ERR_FAILED, the request never sent), which leaves the app on its loading screen,
 * so a load that shows no app header after a while is reloaded.
 *
 * Args:
 *   path: route of the view below the base URL.
 *   ready: selector that is visible once the view rendered.
 *   reroute: whether a load that landed elsewhere is routed again; false keeps a replaced view a failure.
 *
 * Returns:
 *   A step that ends on the view with its animations settled.
 */
function reached(path, ready, reroute = true) {
  const requested = new URL(path, appBaseUrl).pathname;
  return async (page) => {
    let loaded = Date.now();
    let rerouted = 0;
    await expect
      .poll(
        async () => {
          if (!(await page.locator(HEADER).isVisible())) {
            if (Date.now() - loaded > BOOT_PATIENCE_MS) {
              await page.reload();
              loaded = Date.now();
              rerouted = 0;
            }
            return false;
          }
          const here = new URL(page.url()).pathname === requested;
          if (here && (await page.locator(ready).first().isVisible())) return true;
          if (reroute && (!here || (rerouted && Date.now() - rerouted > REROUTE_PATIENCE_MS))) {
            rerouted = Date.now();
            await page.evaluate((target) => {
              const state = { route: target };
              history.pushState(state, "", target);
              dispatchEvent(new PopStateEvent("popstate", { state }));
            }, path);
          }
          return false;
        },
        { timeout: resolveTimeout(60_000), message: `${path} must open the view that shows ${ready}` },
      )
      .toBe(true);
    await animationsSettled(page);
  };
}

/**
 * Args:
 *   page: Playwright page that ends on one view of the signed-in interface.
 *   path: route of the view below the base URL.
 *   ready: selector that is visible once the view rendered.
 */
async function openView(page, path, ready) {
  await gotoOnion(page, `${appBaseUrl}${path}`);
  await reached(path, ready)(page);
}

/**
 * Args:
 *   page: Playwright page signed in as a Superuser; ends with every step of the setup assistant skipped, so the app
 *     opens the view a URL names.
 */
async function skipSetupAssistant(page) {
  await openView(page, "/admin?moduleId=setup-assistant", SETUP_STEP);
  for (let step = 0; step < SETUP_STEP_LIMIT && (await page.locator(SETUP_PENDING_STEP).count()) > 0; step += 1) {
    const pending = await page.locator(SETUP_PENDING_STEP).count();
    await page.locator(`${CONTENT} button.kix-button.form-button`, { hasText: /skip/i }).click();
    await expect
      .poll(() => page.locator(SETUP_PENDING_STEP).count(), {
        timeout: resolveTimeout(30_000),
        message: `a skipped setup step must leave fewer than the ${pending} open ones`,
      })
      .toBeLessThan(pending);
  }
  await expect(page.locator(SETUP_PENDING_STEP), "every setup step must be completed or skipped").toHaveCount(0);
}

async function beforeEach({ page }) {
  expect(appBaseUrl,      "APP_BASE_URL must be set").toBeTruthy();
  expect(canonicalDomain, "CANONICAL_DOMAIN must be set").toBeTruthy();
  expect(oidcIssuerUrl,   "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(logoutUrl,       "LOGOUT_URL must be set").toBeTruthy();
  await page.context().clearCookies();
}

module.exports = {
  env: {
    ssoEnabled,
    appBaseUrl,
    canonicalDomain,
    oidcIssuerUrl,
    logoutUrl,
    kixUserGroupPath,
    biberUsername,
    biberPassword,
    adminUsername,
    adminPassword,
    biberDn,
    userGroupDn,
  },
  selectors: { HEADER, CONTENT, SETUP_STEPS, SETUP_STEP },
  animationsSettled,
  reached,
  openView,
  skipSetupAssistant,
  performKixLogin,
  signInThroughGate,
  runKixLogin,
  runKixLogout,
  runKixLoginLogoutFlow,
  runKixDirectoryLogin,
  runKixDirectoryLogout,
  runKixDirectoryLoginLogoutFlow,
  runKixLdapLoginLogoutFlow,
  expectKeycloakAdminEnv,
  withBiberInGroup,
  withBiberInKixUserGroup,
  beforeEach,
  isServiceEnabled,
  skipUnlessServiceDisabled,
  skipUnlessServiceEnabled,
  runBiberFlow,
  runGuestFlow,
};
