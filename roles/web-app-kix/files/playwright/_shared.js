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
    .not.toContain("/auth");
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
    .not.toContain("/auth");
}

async function runKixDirectoryLogout(page) {
  await inAppLogout(page);

  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator('input[type="password"]').first(),
    "after the in-app logout a protected request must land on the KIX sign-in again",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
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
