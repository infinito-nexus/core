const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const STOREFRONT_HOME = "body.cms-index-index";
const ADMIN_SIGN_IN_FORM = "#login-form #username";

test("rbac: biber without the administrator group is refused at the admin backend and keeps the storefront", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(240_000)); // Keycloak round trip, the refused admin request and the storefront

  const base = normalizeBaseUrl(process.env.APP_BASE_URL || "");
  const username = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
  const password = requireDotenvValue(process.env.BIBER_PASSWORD, "BIBER_PASSWORD");
  const backendPath = requireDotenvValue(process.env.MAGENTO_BACKEND_PATH, "MAGENTO_BACKEND_PATH");
  expect(base, "APP_BASE_URL must be set").toBeTruthy();
  expect(username, "BIBER_USERNAME must be set").toBeTruthy();

  await gotoOnion(page, `${base}${backendPath}`);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the admin backend must hand an anonymous visitor to Keycloak" })
    .toContain("openid-connect/auth");
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the Keycloak sign-in must hand back to Magento" })
    .toContain(base);

  const admin = await gotoOnion(page, `${base}${backendPath}`);
  expect(admin, "the admin backend must answer").toBeTruthy();
  expect(
    admin.status(),
    `the gate of ${backendPath} must refuse a realm user outside the administrator group of web-app-magento`,
  ).toBe(403);
  await expect(page.locator(ADMIN_SIGN_IN_FORM), "a refused user must not get the admin sign-in form").toHaveCount(0);

  const storefront = await gotoOnion(page, `${base}/`);
  expect(storefront, "the storefront must answer").toBeTruthy();
  expect(storefront.status(), "the storefront must stay open to every realm user").toBeLessThan(400);
  await expect(page.locator(STOREFRONT_HOME), "the storefront home page must render for biber").toBeVisible({
    timeout: resolveTimeout(60_000),
  });

  await page.context().clearCookies();
});
