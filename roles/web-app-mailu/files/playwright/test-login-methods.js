const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { decodeDotenvQuotedValue, gotoOnion, safeSkipUnlessEnabled } = require("./personas");

const nativeLoginOffered = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";

function env() {
  const biberEmail = decodeDotenvQuotedValue(process.env.BIBER_EMAIL);
  return {
    baseUrl: decodeDotenvQuotedValue(process.env.MAILU_BASE_URL).replace(/\/$/, ""),
    adminMailbox: `${decodeDotenvQuotedValue(process.env.ADMIN_USERNAME)}@${biberEmail.split("@")[1]}`,
    adminPassword: decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD),
  };
}

function register() {
  test("login methods: with SSO on /sso/login offers the SSO link and no disabled entry", async ({ page }) => {
    safeSkipUnlessEnabled("sso");
    const { baseUrl } = env();
    await gotoOnion(page, `${baseUrl}/sso/login`);
    await expect(page.locator("a[href*='openid-connect/auth']").first(), "expected the OIDC entry of the Mailu fork").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const passwordField = page.locator("form input[name='pw']");
    if (nativeLoginOffered) {
      await expect(passwordField, "expected the local form the native method keeps").toBeVisible({ timeout: resolveTimeout(30_000) });
    } else {
      await expect(passwordField, "the local form must stay hidden while native is off").toBeHidden({ timeout: resolveTimeout(30_000) });
    }
    await expect(page.locator("a[href*='signup']"), "no self-registration entry").toHaveCount(0);
  });

  test("login methods: the administrator mailbox signs in through the break-glass form at /sso/login?fallback=local with SSO on", async ({ page }) => {
    safeSkipUnlessEnabled("sso");
    const { baseUrl, adminMailbox, adminPassword } = env();
    await gotoOnion(page, `${baseUrl}/sso/login?fallback=local`);
    await expect(page.locator("form input[name='pw']"), "the fallback parameter must reveal the local form").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    const response = await page.context().request.post(`${baseUrl}/sso/login?fallback=local`, {
      form: { email: adminMailbox, pw: adminPassword, submitAdmin: "Sign in Admin" },
      maxRedirects: 0,
      failOnStatusCode: false,
      timeout: resolveTimeout(30_000),
    });
    expect(response.status(), "the break-glass form sign-in must redirect into Mailu").toBe(302);
    expect(response.headers()["location"] || "", "the break-glass sign-in must land on the admin interface").toContain("/admin");
  });
}

module.exports = { register };
