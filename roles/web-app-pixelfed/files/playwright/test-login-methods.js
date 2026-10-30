const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

const LOGIN_EMAIL = 'input#email[name="email"]';
const LOGIN_PASSWORD = 'input#password[name="password"]';
const LOGIN_SUBMIT = 'form[action$="/login"] button[type="submit"]';
const SSO_ENTRY = 'a[href="/auth/oidc/start"]';
const SIGN_UP_ENTRY = 'a[href="/register"]';
const MASTODON_ENTRY = 'form[action="/auth/raw/mastodon/start"]';
const TWO_FACTOR_ENROLLMENT = 'a[href$="/settings/security/2fa/setup"]';
const AUTHENTICATED = 'a[title="User Menu"], a[aria-haspopup="true"], a[href="/settings/home"], a[href="/logout"]';

const loginMethodSso = process.env.LOGIN_METHOD_SSO_ENABLED === "true";
const loginMethodNative = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const loginMethodTwoFactor = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const loginMethodRegistration = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";

exports.register = function (shared) {
  const base = () => shared.env.pixelfedBaseUrl.replace(/\/$/, "");
  const adminEmail = decodeDotenvQuotedValue(process.env.ADMIN_EMAIL || "");
  const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

  test("login methods: with SSO on the sign-in page offers the SSO entry and none of the disabled ones", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await gotoOnion(page, `${base()}/login`);

    if (loginMethodSso) {
      await expect(page.locator(SSO_ENTRY).first(), "the OIDC entry must render on the sign-in page").toBeVisible({ timeout: resolveTimeout(60_000) });
    }
    if (!loginMethodNative) {
      await expect(page.locator(LOGIN_EMAIL), "the password form must stay hidden while native sign-in is off").toBeHidden({ timeout: resolveTimeout(30_000) });
      await expect(page.locator(LOGIN_PASSWORD), "the password form must stay hidden while native sign-in is off").toBeHidden({ timeout: resolveTimeout(30_000) });
    }
    if (!loginMethodRegistration) {
      await expect(page.locator(SIGN_UP_ENTRY), "the sign-up entry must be gone while registration is off").toHaveCount(0);
      await expect(page.locator(MASTODON_ENTRY), "the Mastodon sign-in must be gone while registration is off").toHaveCount(0);
    }
  });

  test("login methods: /login?fallback=local signs the administrator in while SSO is on (break-glass)", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    expect(adminEmail, "ADMIN_EMAIL must be set in the Playwright env file").toBeTruthy();
    expect(adminPassword, "ADMIN_PASSWORD must be set in the Playwright env file").toBeTruthy();

    await gotoOnion(page, `${base()}/login?fallback=local`);
    await expect(page.locator(LOGIN_EMAIL), "the break-glass parameter must keep the password form").toBeVisible({ timeout: resolveTimeout(60_000) });
    await page.locator(LOGIN_EMAIL).fill(adminEmail);
    await page.locator(LOGIN_PASSWORD).fill(adminPassword);
    await page.locator(LOGIN_SUBMIT).first().click({ timeout: resolveTimeout(30_000) });
    await expect
      .poll(() => page.url(), {
        timeout: resolveTimeout(60_000),
        message: "the break-glass sign-in must leave /login for an authenticated Pixelfed surface",
      })
      .not.toMatch(/\/login(\?|$)/);
    await expect(page.locator(AUTHENTICATED).first()).toBeVisible({ timeout: resolveTimeout(60_000) });

    if (!loginMethodTwoFactor) {
      await gotoOnion(page, `${base()}/settings/security`);
      await expect(
        page.locator(TWO_FACTOR_ENROLLMENT),
        "the two-factor enrollment must stay hidden while Pixelfed's own second factor is off",
      ).toBeHidden({ timeout: resolveTimeout(30_000) });
    }
  });
};
