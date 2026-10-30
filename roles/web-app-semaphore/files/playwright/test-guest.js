const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { apiGetOnion, assertCspResponseHeader, assertCspMetaParity, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("guest: login reachable, serves CSP, never reaches an authenticated surface", async ({ page }) => {
    const response = await gotoOnion(page, `${shared.env.semaphoreBaseUrl}${shared.LOGIN_PATH}`);
    expect(response, "Expected Semaphore login response").toBeTruthy();
    expect(response.status(), "Expected Semaphore login status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Semaphore URL`,
    ).toBe(true);

    const directives = assertCspResponseHeader(response, "semaphore login");
    await assertCspMetaParity(page, directives, "semaphore login");

    const account = await apiGetOnion(page.request, `${shared.env.semaphoreBaseUrl}/api/user`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(account.status(), "a guest must hold no Semaphore session").toBe(401);

    await gotoOnion(page, `${shared.env.semaphoreBaseUrl}/users`, { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(30_000),
        message: "guest hitting /users must be forced back to the login page",
      })
      .toContain(shared.LOGIN_PATH);
    await expect(page.locator(".auth .v-card"), "the login page must render its sign-in card").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  });

  test("guest: Semaphore's own form rejects empty credentials", async ({ page }) => {
    // nocheck: playwright-sso-ldap-gate -- gates on the password form the native and ldap login methods render, not on a service
    test.skip(!shared.env.passwordFormShown, "the password form is off while only SSO signs in");
    await shared.gotoLogin(page);

    await page.locator("#auth-username").first().fill("");
    await page.locator("#auth-password").first().fill("");
    await page.locator('[data-testid="auth-signin"]').first().click({ timeout: resolveTimeout(30_000) });
    await expect(
      page.locator(".auth .v-messages.error--text .v-messages__message").first(),
      "Semaphore's own login form must reject the empty-credentials submission with a visible error",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    expect(page.url(), "guest must remain on the login page after an empty submit").toContain(shared.LOGIN_PATH);
    const account = await apiGetOnion(page.request, `${shared.env.semaphoreBaseUrl}/api/user`, {
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(account.status(), "the rejected empty submission must leave the guest without a Semaphore session").toBe(401);
  });
};
