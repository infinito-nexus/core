const { test, expect } = require("@playwright/test");

const { assertCspResponseHeader, assertCspMetaParity } = require("./personas");

exports.register = function (shared) {
  test("guest: login reachable, serves CSP, never reaches an authenticated surface", async ({ page }) => {
    const response = await page.goto(`${shared.env.semaphoreBaseUrl}${shared.LOGIN_PATH}`);
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
    await page.locator('[data-testid="auth-signin"]').first().click().catch(() => {});
    await page.waitForTimeout(1500);
    expect(page.url(), "guest must remain on the login page after an empty submit").toContain(shared.LOGIN_PATH);

    await page.goto(`${shared.env.semaphoreBaseUrl}/users`, { waitUntil: "domcontentloaded" });
    await expect(
      page.locator("#auth-username"),
      "guest hitting /users must be forced back to the login form",
    ).toBeVisible({ timeout: 30_000 });
  });
};
