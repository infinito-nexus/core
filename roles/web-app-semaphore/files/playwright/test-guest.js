const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { apiGetOnion, assertCspResponseHeader, assertCspMetaParity, gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("guest: login reachable, serves CSP, Semaphore's own form rejects empty credentials, never reaches an authenticated surface", async ({
    page,
  }) => {
    const response = await gotoOnion(page, `${shared.env.semaphoreBaseUrl}${shared.LOGIN_PATH}`);
    expect(response, "Expected Semaphore login response").toBeTruthy();
    expect(response.status(), "Expected Semaphore login status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the Semaphore URL`,
    ).toBe(true);

    const directives = assertCspResponseHeader(response, "semaphore login");
    await assertCspMetaParity(page, directives, "semaphore login");

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

    await gotoOnion(page, `${shared.env.semaphoreBaseUrl}/users`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator("#auth-username"),
      "guest hitting /users must be forced back to the login form",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
  });
};
