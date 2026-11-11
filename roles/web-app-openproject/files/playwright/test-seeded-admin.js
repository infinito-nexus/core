const { test, expect } = require("@playwright/test");

const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

test.use({ ignoreHTTPSErrors: true });

const base = normalizeBaseUrl(
  requireDotenvValue(
    process.env.OPENPROJECT_BASE_URL || process.env.APP_BASE_URL,
    "OPENPROJECT_BASE_URL or APP_BASE_URL"
  )
).replace(/\/$/, "");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const ssoEnabled = (process.env.SSO_SERVICE_ENABLED || "").toLowerCase() === "true";

const SEEDED_LOGIN = "admin";
const SEEDED_PUBLISHED_PASSWORD = "admin";

test("seeded admin: the upstream account with the published password cannot sign in", async ({ page }) => {
  test.skip(ssoEnabled, "with sso oauth2-proxy sends every request to the identity provider");
  test.skip(adminUsername.toLowerCase() === SEEDED_LOGIN, "the platform administrator owns the seeded login and its password is converged");
  await page.context().clearCookies();
  await gotoOnion(page, `${base}/login`);
  const user = page.locator("#login-form input#username");
  const password = page.locator("#login-form input#password");
  await expect(user).toBeEditable({ timeout: resolveTimeout(10_000) });
  await user.fill(SEEDED_LOGIN);
  await expect(password).toBeEditable({ timeout: resolveTimeout(10_000) });
  await password.fill(SEEDED_PUBLISHED_PASSWORD);
  await page.locator("#login-form [type='submit']").first().click();
  await page.waitForLoadState("domcontentloaded", { timeout: resolveTimeout(30_000) });
  await expect(page.locator("#login-form"), "the sign-in form stays: the seeded account is locked").toBeVisible({ timeout: resolveTimeout(10_000) });
  expect(new URL(page.url()).pathname, "no password change form opens for the seeded account").not.toContain("change_password");
});
