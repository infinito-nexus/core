const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { clickOidcLoginLink, gotoOnion, normalizeBaseUrl, performKeycloakLogin, readEnv } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const VISIBLE_ENROLLMENT = [
  "a[href*='/settings/two_factor_authentication']",
  "a[href*='/settings/otp_authentication']",
  "a[href*='/settings/security_keys']",
]
  .map((selector) => `${selector}:visible`)
  .join(", ");

/**
 * Args:
 *   page: Playwright page on the Mastodon sign-in page.
 *   selector: the entry of a sign-in method.
 *   enabled: whether login.method switches that method on.
 *   label: the method, named in the failure message.
 */
async function expectEntry(page, selector, enabled, label) {
  if (enabled) {
    await expect(page.locator(selector).first(), `${label} is on, so its entry must render`).toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  } else {
    await expect(page.locator(selector), `${label} is off, so its entry must not render`).toHaveCount(0);
  }
}

test("login methods: with sso on the Mastodon sign-in offers Keycloak and no switched-off entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/auth/sign_in`, { waitUntil: "domcontentloaded" });

  const atKeycloak = () => page.url().includes("/protocol/openid-connect/auth");
  const oidcEntry = page
    .locator("a[href*='/auth/auth/openid_connect'], form[action*='/auth/auth/openid_connect']")
    .first();
  await expect
    .poll(async () => atKeycloak() || (await oidcEntry.isVisible().catch(() => false)), {
      timeout: resolveTimeout(60_000),
      message: "the Mastodon sign-in must offer the Keycloak entry or hand over to Keycloak directly",
    })
    .toBe(true);
  if (atKeycloak()) {
    expect(nativeEnabled, "Mastodon may skip its own sign-in page only while OMNIAUTH_ONLY hides the form").toBe(false);
    return;
  }

  await expectEntry(page, "input[name='user[password]']", nativeEnabled, "login.method.native");
  await expectEntry(page, "a[href$='/auth/sign_up']", registrationEnabled && nativeEnabled, "login.method.registration");
});

test("login methods: with sso on the settings offer no second-factor enrollment", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.skip(twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=true keeps Mastodon's own enrollment on");
  test.setTimeout(resolveTimeout(180_000));
  const canonicalDomain = readEnv("CANONICAL_DOMAIN");
  const adminUsername = readEnv("ADMIN_USERNAME");
  const adminPassword = readEnv("ADMIN_PASSWORD");
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/auth/sign_in`, { waitUntil: "domcontentloaded" });
  if (!page.url().includes("openid-connect/auth")) {
    const strictLogin = page.getByRole("link", { name: /^\s*(log\s*in|sign\s*in|sso)\s*$/i }).first();
    const looseLogin = page.getByRole("link", { name: /log\s*in|sign\s*in|sso/i }).first();
    const authPage = await clickOidcLoginLink(page, strictLogin, looseLogin);
    expect(authPage, "the Mastodon sign-in must hand off to Keycloak").toBeTruthy();
  }
  await performKeycloakLogin(page, adminUsername, adminPassword, canonicalDomain);

  await gotoOnion(page, `${appBaseUrl}/auth/edit`, { waitUntil: "load" });
  await expect(
    page.locator("html[data-infinito-2fa-enrollment='hidden']"),
    "the javascript service must inject the enrollment hider while login.method.2fa is off",
  ).toBeAttached({ timeout: resolveTimeout(30_000) });
  await expect(
    page.locator(VISIBLE_ENROLLMENT),
    "login.method.2fa is off, so no second-factor enrollment entry may be visible",
  ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  await page.context().clearCookies();
});
