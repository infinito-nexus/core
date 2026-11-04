const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, performKeycloakLoginForm, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const VISIBLE_ENROLLMENT = [
  "a[href*='/accounts/auth/tokens/']",
  "form[action*='/accounts/auth/tokens/']",
  "#passkey-register-button",
]
  .map((selector) => `${selector}:visible`)
  .join(", ");

/**
 * Args:
 *   page: Playwright page on the Weblate sign-in page.
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

test("login methods: with sso on the Weblate sign-in offers Keycloak and no switched-off entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/accounts/login/`, { waitUntil: "domcontentloaded" });

  const atKeycloak = () => page.url().includes("/protocol/openid-connect/auth");
  const oidcEntry = page.locator("a[href*='/accounts/login/oidc/'], form[action*='/accounts/login/oidc/']").first();
  await expect
    .poll(async () => atKeycloak() || (await oidcEntry.isVisible().catch(() => false)), {
      timeout: resolveTimeout(60_000),
      message: "the Weblate sign-in must offer the Keycloak entry or hand over to Keycloak directly",
    })
    .toBe(true);
  if (atKeycloak()) {
    expect(nativeEnabled, "Weblate may skip its own sign-in page only while no local form is offered").toBe(false);
    return;
  }

  await expectEntry(page, "input[name='password']", nativeEnabled, "login.method.native");
  await expectEntry(page, "a[href*='/accounts/register/']", registrationEnabled, "login.method.registration");
});

test("login methods: with sso on the account settings offer no second-factor enrollment", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.skip(twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=true keeps Weblate's own enrollment on");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/accounts/login/`, { waitUntil: "domcontentloaded" });
  if (!page.url().includes("/protocol/openid-connect/auth")) {
    await page
      .locator("form[action*='/accounts/login/oidc/'] button, a[href*='/accounts/login/oidc/']")
      .first()
      .click({ timeout: resolveTimeout(30_000) });
  }
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "the sign-in must reach Keycloak" })
    .toContain("/protocol/openid-connect/auth");
  await performKeycloakLoginForm(page, adminUsername, adminPassword);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(90_000), message: "Keycloak must return to Weblate" })
    .toContain(new URL(appBaseUrl).host);

  await gotoOnion(page, `${appBaseUrl}/accounts/profile/`, { waitUntil: "load" });
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
