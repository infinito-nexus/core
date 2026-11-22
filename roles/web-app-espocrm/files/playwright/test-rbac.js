const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isOidcCodeExchange } = require("./_shared");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");
const {
  clickOidcLoginLink,
  decodeDotenvQuotedValue,
  gotoOnion,
  keycloakAdminAddUserToGroup,
  keycloakRemoveUserFromGroupViaRest,
  normalizeBaseUrl,
  performKeycloakLoginForm,
} = require("./personas");

const env = {
  appBaseUrl: normalizeBaseUrl(process.env.APP_BASE_URL || ""),
  keycloakBaseUrl: normalizeBaseUrl(process.env.KEYCLOAK_BASE_URL || ""),
  realmName: decodeDotenvQuotedValue(process.env.KEYCLOAK_REALM_NAME || ""),
  superAdminUsername: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_USERNAME || ""),
  superAdminPassword: decodeDotenvQuotedValue(process.env.SUPER_ADMIN_PASSWORD || ""),
  biberUsername: decodeDotenvQuotedValue(process.env.BIBER_USERNAME || ""),
  biberPassword: decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || ""),
  userGroup: decodeDotenvQuotedValue(process.env.RBAC_GROUP_USER || ""),
  managerGroup: decodeDotenvQuotedValue(process.env.RBAC_GROUP_MANAGER || ""),
  administratorGroup: decodeDotenvQuotedValue(process.env.RBAC_GROUP_ADMINISTRATOR || ""),
  userTeam: decodeDotenvQuotedValue(process.env.ESPOCRM_TEAM_USER || ""),
  managerTeam: decodeDotenvQuotedValue(process.env.ESPOCRM_TEAM_MANAGER || ""),
};

async function submitKeycloakSignIn(page) {
  await page.context().clearCookies();
  await gotoOnion(page, `${env.appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  const loginResponse = page.context().waitForEvent("response", {
    predicate: isOidcCodeExchange,
    timeout: resolveTimeout(120_000),
  });
  loginResponse.catch(() => {});
  let authPage = page;
  if (!page.url().includes("openid-connect/auth")) {
    const strictLogin = page
      .getByRole("link", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i })
      .or(page.getByRole("button", { name: /^\s*(log\s*in|sign\s*in|login|sso)\s*$/i }))
      .first();
    const looseLogin = page
      .getByRole("link", { name: /log\s*in|sign\s*in|sso/i })
      .or(page.getByRole("button", { name: /log\s*in|sign\s*in|sso/i }))
      .first();
    authPage = (await clickOidcLoginLink(page, strictLogin, looseLogin)) || page;
  }
  await performKeycloakLoginForm(authPage, env.biberUsername, env.biberPassword);
  return loginResponse;
}

async function signInThroughKeycloak(page) {
  const loginResponse = await submitKeycloakSignIn(page);
  expect(loginResponse.status(), "EspoCRM must accept the code of a role-group member").toBe(200);
  await expect
    .poll(
      async () => (await page.context().cookies()).some((cookie) => cookie.name === "auth-token"),
      { timeout: resolveTimeout(90_000), message: "EspoCRM stores its auth-token cookie once the OIDC sign-in lands" },
    )
    .toBe(true);
}

async function currentUser(page) {
  const response = await page.request.get(`${env.appBaseUrl}/api/v1/App/user`, { timeout: resolveTimeout(60_000) });
  expect(response.status(), "App/user must answer for a signed-in user").toBe(200);
  return response.json();
}

async function accountListStatus(page) {
  const response = await page.request.get(`${env.appBaseUrl}/api/v1/Account?maxSize=1`, { timeout: resolveTimeout(60_000) });
  return response.status();
}

async function signOut(page) {
  await page
    .locator(".navbar .menu-container a.dropdown-toggle, #nav-menu-dropdown")
    .first()
    .click({ timeout: resolveTimeout(15_000) })
    .then(() => page.locator('[data-action="logout"]').first().click({ timeout: resolveTimeout(15_000) }))
    .catch(() => {});
  await page.context().clearCookies();
}

async function withBiberIn(browser, groupPath, body) {
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  let joined = false;
  try {
    joined = await keycloakAdminAddUserToGroup(
      admin.request,
      env.keycloakBaseUrl,
      env.realmName,
      groupPath,
      env.biberUsername,
      env.superAdminUsername,
      env.superAdminPassword,
    );
    await body();
  } finally {
    if (joined) {
      await keycloakRemoveUserFromGroupViaRest(
        admin.request,
        env.keycloakBaseUrl,
        env.realmName,
        env.superAdminUsername,
        env.superAdminPassword,
        groupPath,
        env.biberUsername,
      ).catch((err) => console.warn(`Cleanup removal of biber from ${groupPath} failed: ${err}`));
    }
    await admin.close().catch(() => {});
  }
}

test.describe.serial("espocrm RBAC", () => {
  test("biber: Keycloak sign-in outside every EspoCRM role group is refused", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(180_000)); // OIDC round-trip plus the refused code exchange

    const loginResponse = await submitKeycloakSignIn(page);
    expect(loginResponse.status(), "the role-group OIDC user provider must refuse a user without a role group").toBe(401);
    expect(
      (await page.context().cookies()).some((cookie) => cookie.name === "auth-token"),
      "a refused sign-in must not leave an EspoCRM session",
    ).toBe(false);
    await page.context().clearCookies();
  });

  test("biber: the administrator group promotes at sign-in and leaving it demotes", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(360_000)); // two group joins, two OIDC round-trips and teardown

    await withBiberIn(browser, env.userGroup, async () => {
      await withBiberIn(browser, env.administratorGroup, async () => {
        await signInThroughKeycloak(page);
        const { user } = await currentUser(page);
        expect(user.type, "the administrator group must make biber an EspoCRM administrator at sign-in").toBe("admin");
        await signOut(page);
      });
      await signInThroughKeycloak(page);
      const { user } = await currentUser(page);
      expect(user.type, "leaving the administrator group must make biber a regular user at the next sign-in").toBe("regular");
      expect(Object.values(user.teamsNames || {}), "the user group must keep the Users team").toContain(env.userTeam);
      await signOut(page);
    });
  });

  test("biber: the user group grants the Users team and team read access", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, OIDC round-trip and teardown

    await withBiberIn(browser, env.userGroup, async () => {
      await signInThroughKeycloak(page);
      const { user, acl } = await currentUser(page);
      expect(Object.values(user.teamsNames || {}), "the user group must map onto the Users team").toContain(env.userTeam);
      expect(await accountListStatus(page), "the Users team must open the account list").toBe(200);
      expect(acl.table.Account.delete, "the User role must not delete accounts").toBe("no");
      await signOut(page);
    });
  });

  test("biber: the manager group grants the Managers team and full record access", async ({ page, browser }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // group join, OIDC round-trip and teardown

    await withBiberIn(browser, env.managerGroup, async () => {
      await signInThroughKeycloak(page);
      const { user, acl } = await currentUser(page);
      expect(Object.values(user.teamsNames || {}), "the manager group must map onto the Managers team").toContain(env.managerTeam);
      expect(acl.table.Account.delete, "the Manager role must delete every account").toBe("all");
      expect(user.type, "the manager group must not make biber an administrator").toBe("regular");
      await signOut(page);
    });
  });

  test("biber: LDAP sign-in outside every role group is refused", async ({ request }) => {
    skipUnlessServiceEnabled("ldap");
    skipUnlessServiceDisabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // directory bind through EspoCRM

    const credentials = Buffer.from(`${env.biberUsername}:${env.biberPassword}`).toString("base64");
    const response = await request.get(`${env.appBaseUrl}/api/v1/App/user`, {
      headers: { "Espo-Authorization": credentials },
      timeout: resolveTimeout(60_000),
    });
    expect(response.status(), "ldapUserLoginFilter admits only members of a declared role group").toBe(401);
  });
});
