const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { performKeycloakLoginForm } = require("./personas");

exports.register = function (shared) {
  test("biber: Semaphore OIDC login refuses biber without a Semaphore role group", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(90_000)); // OIDC round-trip via Keycloak
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
    expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

    await shared.gotoLogin(page);
    const oidcButton = page
      .locator("a, button")
      .filter({ hasText: /sign\s*in\s*with|keycloak|single\s*sign|sso/i })
      .first();
    await expect(oidcButton, 'the "Sign in with Keycloak" button must render on the Semaphore login page').toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await oidcButton.click({ timeout: resolveTimeout(30_000) });
    await expect
      .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "expected redirect to Keycloak OIDC auth" })
      .toContain(`${shared.env.oidcIssuerUrl}/protocol/openid-connect/auth`);

    await performKeycloakLoginForm(page, shared.env.biberUsername, shared.env.biberPassword);

    await expect
      .poll(() => shared.onLoginPage(page) && !page.url().includes("/protocol/openid-connect/"), {
        timeout: resolveTimeout(60_000),
        message: "the email claim template yields no email for biber, so Semaphore MUST send the callback back to its login page",
      })
      .toBe(true);
    const account = await page.request.get(`${shared.env.semaphoreBaseUrl}/api/user`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(account.status(), "biber outside the administrator and user groups MUST NOT hold a Semaphore session").toBe(401);
  });

  test("biber: membership in the user group admits biber through the Semaphore OIDC login", async ({ browser }) => {
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(120_000)); // Keycloak group write plus the OIDC round-trip
    expect(shared.env.userGroupPath, "RBAC_USER_GROUP_PATH must be set").toBeTruthy();

    await shared.withBiberInGroup(browser, shared.env.userGroupPath, async () => {
      const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
      try {
        const page = await ctx.newPage();
        await page.setViewportSize({ width: 1440, height: 1100 });
        await shared.signInViaOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber");

        await expect(page.locator("body")).toContainText(/dashboard|project|task|new project/i, { timeout: resolveTimeout(60_000) });
        const account = await shared.currentUser(page);
        expect(
          account.admin,
          `a user-group member MUST NOT carry the Semaphore admin flag (account: ${JSON.stringify(account)})`,
        ).toBe(false);
        expect(
          String(account.email).toLowerCase(),
          `Semaphore MUST take the account email from the OIDC email claim (account: ${JSON.stringify(account)})`,
        ).toBe(shared.env.biberEmail.toLowerCase());

        const menu = await shared.openAccountMenu(page, "biber");
        await expect(
          page.locator('a[href$="/users"]').or(menu.locator(".v-list-item:has(.mdi-account-multiple)")),
          "biber: the open account menu of a user-group member must offer no user administration",
        ).toHaveCount(0);
        await shared.signOutFromMenu(page, menu, "biber");
      } finally {
        await ctx.close().catch(() => {});
      }
    });
  });
};
