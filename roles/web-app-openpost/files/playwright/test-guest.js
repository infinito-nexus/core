const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { assertCspResponseHeader, assertCspMetaParity, gotoOnion } = require("./personas");
const { isServiceEnabled } = require("./service-gating");

exports.register = function (shared) {
  test("guest: login serves CSP, refuses wrong and empty credentials, never reaches the desk", async ({ page }) => {
    test.setTimeout(resolveTimeout(90_000)); // optional Keycloak round-trip for the IdP rejection
    const response = await shared.gotoLogin(page);
    expect(response, "Expected an OpenPost login response").toBeTruthy();
    expect(response.status(), "Expected the OpenPost login status to be < 400").toBeLessThan(400);
    expect(
      response.url().includes(shared.env.canonicalDomain),
      `Expected canonical domain "${shared.env.canonicalDomain}" to back the OpenPost URL`,
    ).toBe(true);

    const directives = assertCspResponseHeader(response, "openpost login");
    await assertCspMetaParity(page, directives, "openpost login");

    await page.locator("#email").fill("guest@invalid.example");
    await page.locator("#password").fill("not-a-valid-password");
    await page.locator("form").filter({ has: page.locator("#password") }).locator('button[type="submit"]').click();
    await expect(page.getByRole("alert").or(page.locator('[role="status"], .text-destructive')).first(),
      "guest: wrong credentials must produce a visible error").toBeVisible({ timeout: resolveTimeout(30_000) });
    expect(shared.onLoginPage(page), "guest must remain on the login page after a rejected sign-in").toBe(true);

    await gotoOnion(page, `${shared.env.appBaseUrl}/settings`, { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => shared.onLoginPage(page), {
        timeout: resolveTimeout(30_000),
        message: "guest hitting /settings must be forced back to the login page",
      })
      .toBe(true);

    if (isServiceEnabled("sso")) {
      await shared.oidcProviderButton(page).click();
      await expect
        .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "guest: expected the Keycloak login form" })
        .toContain(`${shared.env.oidcIssuerUrl}/protocol/openid-connect/auth`);
      await page.locator("#kc-login, input[type='submit'], button[type='submit']").first().click();
      await expect(page.locator("#username, input[name='username']").first(),
        "guest: Keycloak must reject the empty submission and keep its login form").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
      expect(page.url(), "guest: an empty Keycloak submission must not return to OpenPost").toContain(
        shared.env.oidcIssuerUrl,
      );
    }
  });
};
