const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const internalLogin = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";

function register() {
  test("login methods: with SSO on the login page offers the OAuth2 entry and no disabled entry", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const base = decodeDotenvQuotedValue(process.env.APP_BASE_URL).replace(/\/$/, "");
    await gotoOnion(page, `${base}/login`);
    if (page.url().includes("openid-connect/auth")) {
      await performKeycloakLoginForm(
        page,
        decodeDotenvQuotedValue(process.env.ADMIN_USERNAME),
        decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
      );
      await expect.poll(() => page.url(), { timeout: resolveTimeout(60_000) }).toContain(base);
      await gotoOnion(page, `${base}/login`);
    }
    await expect(page.locator("button[name='oauth2_button']"), "expected the Keycloak OAuth2 entry").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const internalEntries = page.locator("input[name='email'], button[name='internal_button']");
    if (internalLogin) {
      await expect(internalEntries.first(), "expected the internal form the native method keeps").toBeVisible();
      return;
    }
    await expect(internalEntries, "AUTHENTICATION_SOURCES must drop the internal form while native is off").toHaveCount(0);
    await expect(page.getByRole("link", { name: /Forgotten your password/ })).toHaveCount(0);
  });
}

module.exports = { register };
