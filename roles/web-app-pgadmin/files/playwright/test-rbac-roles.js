const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");
const keycloakAdmin = require("./personas/utils/keycloak");

test.use({ ignoreHTTPSErrors: true });

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || "").replace(/\/$/, ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  keycloakAdminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  keycloakAdminCliClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  adminUsername: decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
  adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  biberEmail: decodeDotenvQuotedValue(process.env.BIBER_EMAIL),
  userGroupPath: decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH),
};

/**
 * Run `fn` while biber is a member of the Keycloak group at `groupPath`,
 * removing the membership afterwards only when this call granted it.
 *
 * Args:
 *   browser: the Playwright browser, used for an isolated admin context.
 *   groupPath: the full Keycloak group path, with leading slash.
 *   fn: async body executed while the membership holds.
 */
async function withBiberInGroup(browser, groupPath, fn) {
  const adminOpts = { adminRealm: env.keycloakAdminRealm, adminClientId: env.keycloakAdminCliClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let biberAdded = false;
  try {
    biberAdded = await keycloakAdmin.keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    return await fn();
  } finally {
    if (biberAdded) {
      await keycloakAdmin
        .keycloakRemoveUserFromGroupViaRest(
          adminCtx.request,
          env.keycloakBaseUrl,
          env.realmName,
          env.superAdminUsername,
          env.superAdminPassword,
          groupPath,
          env.biberUsername,
          adminOpts,
        )
        .catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

/**
 * Start the pgAdmin OAuth2 login and complete the Keycloak form.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the Keycloak login name.
 *   password: the Keycloak password.
 */
async function loginWithOauth2(page, username, password) {
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  const oauth2Button = page
    .getByRole("button", { name: /login with/i })
    .or(page.locator("button[name='oauth2_button']"))
    .first();
  await expect(oauth2Button, "the pgAdmin login page MUST offer the Keycloak OAuth2 button").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await oauth2Button.click({ timeout: resolveTimeout(30_000) });
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the OAuth2 button to lead to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, username, password);
}

/**
 * Return pgAdmin's view of the signed-in account from current_user.js.
 *
 * Args:
 *   page: a Playwright page whose context carries the pgAdmin session.
 */
async function currentUser(page) {
  const response = await page.request.get(`${env.appBaseUrl}/user_management/current_user.js`, {
    failOnStatusCode: false,
    maxRedirects: 0,
    timeout: resolveTimeout(30_000),
  });
  const text = response.ok() ? await response.text() : "";
  const field = (name) => (text.match(new RegExp(`['"]?${name}['"]?\\s*:\\s*['"]?([^'",\\n]*)`)) || [])[1];
  return {
    status: response.status(),
    isAdmin: field("is_admin"),
    email: field("email"),
    authSource: field("current_auth_source"),
  };
}

/**
 * Wait until pgAdmin serves its browser surface to the signed-in account.
 *
 * Args:
 *   page: a Playwright page that just completed the OAuth2 login.
 *   label: the account named in failure messages.
 */
async function expectSignedIn(page, label) {
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `${label} MUST land in pgAdmin after the OAuth2 login` })
    .toContain("/browser");
  await expect
    .poll(async () => (await currentUser(page)).status, { timeout: resolveTimeout(30_000) })
    .toBe(200);
}

test("rbac: biber without a pgAdmin role group is refused by the OAuth2 claim check", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak round-trip plus the pgAdmin callback
  await loginWithOauth2(page, env.biberUsername, env.biberPassword);
  await expect(page.locator("body")).toContainText(/not authorized to login/i, { timeout: resolveTimeout(60_000) });
  expect((await currentUser(page)).status, "biber MUST NOT hold a pgAdmin session").not.toBe(200);
});

test("rbac: membership in the user group signs biber in with the pgAdmin User role", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000)); // Keycloak group join, Keycloak round-trip and the pgAdmin callback
  await withBiberInGroup(browser, env.userGroupPath, async () => {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await ctx.newPage();
      await loginWithOauth2(page, env.biberUsername, env.biberPassword);
      await expectSignedIn(page, "biber");
      const account = await currentUser(page);
      expect(account.authSource, "biber MUST be signed in through OAuth2").toBe("oauth2");
      expect(account.isAdmin, "a user-group member MUST NOT be a pgAdmin Administrator").toBe("false");
      expect(account.email, "pgAdmin MUST take the account email from the OIDC email claim").toBe(env.biberEmail);
      const users = await page.request.get(`${env.appBaseUrl}/user_management/user/`, {
        failOnStatusCode: false,
        maxRedirects: 0,
      });
      expect(users.status(), "a pgAdmin User MUST NOT reach the user management").toBeGreaterThanOrEqual(400);
    } finally {
      await ctx.close().catch(() => {});
    }
  });
});

test("rbac: the administrator group member signs in through OAuth2 as a pgAdmin Administrator", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000)); // Keycloak round-trip plus the pgAdmin callback
  await loginWithOauth2(page, env.adminUsername, env.adminPassword);
  await expectSignedIn(page, "administrator");
  const account = await currentUser(page);
  expect(account.authSource, "the administrator MUST be signed in through OAuth2").toBe("oauth2");
  expect(account.isAdmin, "the deploy-time reconcile MUST grant the administrator group member the Administrator role").toBe("true");
  const users = await page.request.get(`${env.appBaseUrl}/user_management/user/`, {
    failOnStatusCode: false,
    maxRedirects: 0,
  });
  expect(users.status(), "a pgAdmin Administrator MUST reach the user management").toBe(200);
});
