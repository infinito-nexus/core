const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const nativeOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";

function register() {
  test("login methods: with SSO on the sign-in page hands over to Keycloak unless the native method is on", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
    await gotoOnion(page, `${base}/admin/login`);
    if (nativeOffered) {
      await expect(page.locator("form[action$='/admin/login'] input[name='password']"), "expected the password form the native method keeps").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
      return;
    }
    await page.waitForURL(/openid-connect\/auth/, { timeout: resolveTimeout(60_000) });
    expect(page.url(), "the OIDC form must be the only entry Listmonk leaves on its sign-in page").toContain("openid-connect/auth");
  });
}

module.exports = { register };
