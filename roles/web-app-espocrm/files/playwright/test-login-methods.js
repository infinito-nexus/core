const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";

test("login methods: with sso on the EspoCRM sign-in offers Keycloak and no password form", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/`);
  await expect(
    page.locator("#login #sign-in"),
    "authenticationMethod Oidc must render the Keycloak sign-in button",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  const passwordField = page.locator("#login #field-password");
  if (nativeEnabled) {
    await expect(passwordField, "login.method.native sets oidcFallback, so the form must render").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  } else {
    await expect(passwordField, "oidcFallback=false must keep the password form off the sign-in page").toBeHidden({
      timeout: resolveTimeout(30_000),
    });
  }
});
