const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled, skipUnlessServiceEnabled, skipUnlessServiceDisabled } = require("./service-gating");
const { skipUnlessAddonEnabled } = require("./addon-gating");
const {
  assertUnauthenticatedLanding,
  decodeDotenvQuotedValue,
  gotoOnion,
  inAppLogout,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginExpectingDenial,
  performKeycloakLoginForm,
  requireDotenvValue,
  withLdapGroupMember,
} = require("./personas");
const { openManagementSurface, withAdminSession } = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const env = {
  baseUrl: normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL")).replace(/\/$/, ""),
  canonicalDomain: requireDotenvValue(process.env.CANONICAL_DOMAIN, "CANONICAL_DOMAIN"),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME),
  adminRealm: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_REALM),
  adminClientId: decodeDotenvQuotedValue(process.env.KEYCLOAK_ADMIN_CLI_CLIENT_ID),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD),
  adminUsername: requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"),
  gitlabBotUsername: requireDotenvValue(process.env.GITLAB_BOT_USERNAME, "GITLAB_BOT_USERNAME"),
  userGroupPath: decodeDotenvQuotedValue(process.env.RBAC_USER_GROUP_PATH),
  biberDn: requireDotenvValue(process.env.BIBER_LDAP_DN, "BIBER_LDAP_DN"),
  userGroupDn: requireDotenvValue(process.env.LDAP_USER_GROUP_DN, "LDAP_USER_GROUP_DN"),
};

async function usersCollectionStatus(page) {
  const response = await page.request.get(`${env.baseUrl}/api/v3/users?pageSize=1`, {
    headers: { Accept: "application/hal+json" },
  });
  return response.status();
}

async function currentUser(page) {
  const response = await page.request.get(`${env.baseUrl}/api/v3/users/me`, {
    headers: { Accept: "application/hal+json" },
  });
  const body = await response.text();
  try {
    return { status: response.status(), body, user: JSON.parse(body) };
  } catch {
    return { status: response.status(), body, user: {} };
  }
}

async function userByLogin(page, login) {
  const filters = JSON.stringify([{ login: { operator: "=", values: [login] } }]);
  const response = await page.request.get(`${env.baseUrl}/api/v3/users?filters=${encodeURIComponent(filters)}`, {
    headers: { Accept: "application/hal+json" },
  });
  expect(response.status(), "an administrator session must be served the users collection").toBe(200);
  const elements = ((await response.json())._embedded || {}).elements || [];
  return elements.find((element) => String(element.login || "").toLowerCase() === login.toLowerCase());
}

async function withBiberInUserGroup(browser, body) {
  const adminOpts = { adminRealm: env.adminRealm, adminClientId: env.adminClientId };
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      adminCtx.request,
      env.keycloakBaseUrl,
      env.realmName,
      env.userGroupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
      adminOpts,
    );
    await body();
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        adminCtx.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        env.userGroupPath,
        env.biberUsername,
        adminOpts,
      ).catch((err) => console.warn(`Cleanup removal of biber from ${env.userGroupPath} failed: ${err}`));
    }
    await adminCtx.close().catch(() => {});
  }
}

test("rbac: biber without an OpenProject role is denied at the oauth2-proxy gate", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${env.baseUrl}/`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginExpectingDenial(page, env.biberUsername, env.biberPassword, env.canonicalDomain);
  const sessionCookies = await page.context().cookies(env.baseUrl);
  expect(
    sessionCookies.some((cookie) => cookie.name === "_open_project_session"),
    "a user outside the administrator and user role groups must not get an OpenProject session",
  ).toBe(false);
});

async function biberSignsInOverTheHeaderBridge(browser) {
  await withBiberInUserGroup(browser, async () => {
    const biberCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    try {
      const page = await biberCtx.newPage();
      await gotoOnion(page, `${env.baseUrl}/`);
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected the oauth2-proxy redirect to Keycloak" })
        .toContain("openid-connect/auth");
      await performKeycloakLoginForm(page, env.biberUsername, env.biberPassword);
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: `expected redirect back to ${env.baseUrl}` })
        .toContain(env.baseUrl);
      await expect(
        page.locator("header.op-app-header"),
        "a user-group member must reach the OpenProject application",
      ).toBeVisible({ timeout: resolveTimeout(60_000) });

      const me = await currentUser(page);
      expect(me.status, `the trusted-header bridge must provision biber, got ${me.status}: ${me.body.slice(0, 300)}`).toBe(200);
      expect(String(me.user.login || "").toLowerCase()).toBe(env.biberUsername.toLowerCase());
      expect(me.user.admin, "a user-group member must not hold the OpenProject admin flag").not.toBe(true);
      expect(
        await usersCollectionStatus(page),
        "a user-group member must not reach the administrator-only user collection",
      ).toBe(403);
    } finally {
      await biberCtx.close().catch(() => {});
    }
  });
}

async function biberSignsInOverTheLdapLogin(page) {
  test.setTimeout(resolveTimeout(180_000));
  await withLdapGroupMember(env.userGroupDn, env.biberDn, async () => {
    await page.context().clearCookies();
    await gotoOnion(page, `${env.baseUrl}/login`);
    const username = page.locator("#login-form input#username");
    const password = page.locator("#login-form input#password");
    await expect(username).toBeEditable({ timeout: resolveTimeout(30_000) });
    await username.fill(env.biberUsername);
    await password.fill(env.biberPassword);
    await page.locator("#login-form [type='submit']").first().click();
    await expect(
      page.locator("header.op-app-header"),
      "the LDAP filter_string must admit a directory user in the user role group",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const me = await currentUser(page);
    expect(me.status, `the LDAP login must give biber a session, got ${me.status}: ${me.body.slice(0, 300)}`).toBe(200);
    expect(String(me.user.login || "").toLowerCase()).toBe(env.biberUsername.toLowerCase());
    expect(me.user.admin, "a user-group member must not hold the OpenProject admin flag").not.toBe(true);
    expect(
      await usersCollectionStatus(page),
      "a user-group member must not reach the administrator-only user collection",
    ).toBe(403);

    await openManagementSurface(page);
    await inAppLogout(page);
    await assertUnauthenticatedLanding(page, env.baseUrl);
  });
}

test("biber: the LDAP login refuses biber without an OpenProject role", async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${env.baseUrl}/login`);
  const username = page.locator("#login-form input#username");
  const password = page.locator("#login-form input#password");
  await expect(username).toBeEditable({ timeout: resolveTimeout(30_000) });
  await username.fill(env.biberUsername);
  await password.fill(env.biberPassword);
  await page.locator("#login-form [type='submit']").first().click();
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) });
  await expect(
    page.locator("#login-form"),
    "the LDAP filter_string must refuse a directory user outside the administrator and user role groups",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  const me = await currentUser(page);
  expect(
    String(me.user.login || "").toLowerCase(),
    `a refused LDAP login must not leave an OpenProject session (got ${me.status}: ${me.body.slice(0, 200)})`,
  ).not.toBe(env.biberUsername.toLowerCase());
});

test("biber: in the user group, signs in to OpenProject without administrator rights", async ({ browser, page }) => {
  skipUnlessServiceEnabled("ldap");
  if (isServiceEnabled("sso")) {
    await biberSignsInOverTheHeaderBridge(browser);
  } else {
    await biberSignsInOverTheLdapLogin(page);
  }
});

test("rbac: the administrator holds OpenProject administrator rights", async ({ page }) => {
  await page.context().clearCookies();
  await withAdminSession(page, async (adminPage) => {
    const me = await currentUser(adminPage);
    expect(String(me.user.login || "").toLowerCase()).toBe(env.adminUsername.toLowerCase());
    expect(me.user.admin, "the role group reconcile must keep the bootstrap administrator an OpenProject admin").toBe(true);
    expect(
      await usersCollectionStatus(adminPage),
      "the administrator role must grant access to the administrator-only user collection",
    ).toBe(200);
  });
});

test("rbac: the role group reconcile keeps the GitLab bot an OpenProject admin", async ({ page }) => {
  skipUnlessAddonEnabled("gitlab_integration");
  skipUnlessServiceDisabled("sso");
  await page.context().clearCookies();
  await withAdminSession(page, async (adminPage) => {
    const bot = await userByLogin(adminPage, env.gitlabBotUsername);
    expect(bot, `the GitLab bot ${env.gitlabBotUsername} must exist`).toBeTruthy();
    expect(bot.admin, "the reconcile must spare the GitLab bot, which holds no administrator role group").toBe(true);
  });
});
