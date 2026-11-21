const { test, expect } = require("@playwright/test");

const { decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const CONTROL = `${normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"))}/control`;
const breakglassEmail = decodeDotenvQuotedValue(process.env.BREAKGLASS_EMAIL);
const breakglassPassword = decodeDotenvQuotedValue(process.env.BREAKGLASS_PASSWORD);
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";
const SIGN_IN_FORM = "form.form-signin";
const FRAME = "nav.navbar.navbar-inverse";

test.use({ ignoreHTTPSErrors: true });

test("guest: with SSO on the sign-in page offers the SSO entry and no disabled method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${CONTROL}/login`);

  await expect(
    page.locator(`${SIGN_IN_FORM} a[href*='openid-connect/auth']`).first(),
    "the Keycloak entry must render on the pretix sign-in page",
  ).toBeVisible({ timeout: resolveTimeout(30_000) });
  if (!nativeEnabled) {
    for (const selector of [
      `${SIGN_IN_FORM} input[name='email']`,
      `${SIGN_IN_FORM} input[name='password']`,
      `${SIGN_IN_FORM} button[type='submit']`,
      `${SIGN_IN_FORM} .nav-pills a[href*='backend=native']`,
      `${SIGN_IN_FORM} a[href$='/control/forgot']`,
    ]) {
      await expect(page.locator(selector), `${selector} must stay hidden while the native method is off`).toBeHidden({
        timeout: resolveTimeout(10_000),
      });
    }
  }
  if (!registrationEnabled) {
    await expect(
      page.locator(`${SIGN_IN_FORM} a[href$='/control/register']`),
      "the registration entry must not render while the registration method is off",
    ).toHaveCount(0);
  }
});

test("administrator: the break-glass account signs in through ?backend=native while SSO is on", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(breakglassEmail, "BREAKGLASS_EMAIL must be set").toBeTruthy();
  expect(breakglassPassword, "BREAKGLASS_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
  await gotoOnion(page, `${CONTROL}/login?backend=native`);

  const email = page.locator(`${SIGN_IN_FORM} input[name='email']`);
  const password = page.locator(`${SIGN_IN_FORM} input[name='password']`);
  await expect(email, "the break-glass form must stay reachable through ?backend=native").toBeEditable({
    timeout: resolveTimeout(10_000),
  });
  await email.fill(breakglassEmail);
  await password.fill(breakglassPassword);
  await page.locator(`${SIGN_IN_FORM} button[type='submit'].btn-primary`).click();

  const alert = page.locator(`${SIGN_IN_FORM} .alert`);
  await expect(page.locator(`${FRAME}, ${SIGN_IN_FORM} .alert`).first(), `sign-in stalled on ${page.url()}`).toBeVisible({
    timeout: resolveTimeout(30_000),
  });
  await expect(alert, `break-glass sign-in rejected: ${(await alert.allInnerTexts()).join(" ")}`).toHaveCount(0);
  await expect(page.locator(FRAME), "the break-glass account must reach the control panel").toBeVisible();
});
