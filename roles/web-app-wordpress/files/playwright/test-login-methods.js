const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

exports.register = function (shared) {
  test("login methods: with sso on wp-login.php offers Keycloak and no switched-off entry", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-login.php`, { waitUntil: "domcontentloaded" });
    if (nativeEnabled) {
      await expect(
        page.locator(".openid-connect-login-button a").first(),
        "login_type button must render the Keycloak entry beside the form",
      ).toBeVisible({ timeout: resolveTimeout(60_000) });
      await expect(page.locator("#user_pass"), "login.method.native is on, so the form must render").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    } else {
      await expect
        .poll(() => page.url(), {
          timeout: resolveTimeout(60_000),
          message: "login_type auto must send wp-login.php to Keycloak instead of rendering the WordPress form",
        })
        .toContain("/protocol/openid-connect/auth");
    }

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-login.php?action=register`, { waitUntil: "domcontentloaded" });
    if (registrationEnabled && nativeEnabled) {
      await expect(page.locator("#registerform"), "login.method.registration is on, so the form must render").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    } else {
      await expect(page.locator("#registerform"), "self-registration must stay closed").toHaveCount(0);
    }
    await shared.wpSignOut(page, shared.env.wpBaseUrl);
  });

  test("break-glass: the local administrator signs in with a direct wp-login.php POST while sso is on", async ({
    page,
  }) => {
    skipUnlessServiceEnabled("sso");
    expect(shared.env.localAdminUsername, "WORDPRESS_ADMIN_USERNAME must be set").toBeTruthy();
    expect(shared.env.localAdminPassword, "WORDPRESS_ADMIN_PASSWORD must be set").toBeTruthy();
    const response = await page.request.post(`${shared.env.wpBaseUrl}/wp-login.php`, {
      form: {
        log: shared.env.localAdminUsername,
        pwd: shared.env.localAdminPassword,
        "wp-submit": "Log In",
        redirect_to: `${shared.env.wpBaseUrl}/wp-admin/`,
      },
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: resolveTimeout(60_000),
    });
    expect(response.status(), "WordPress must accept the local password and redirect").toBe(302);
    expect(response.headers()["location"] || "", "the redirect must lead into the administration").toContain("/wp-admin");

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/`, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#wpadminbar"), "the break-glass session must reach the administration").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
    await shared.wpSignOut(page, shared.env.wpBaseUrl);
  });
};
