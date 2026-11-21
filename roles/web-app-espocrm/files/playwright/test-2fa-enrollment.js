const crypto = require("crypto");
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminNativePassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD || "");
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";
const REQUIRED_MODAL = ".modal:has(button[data-action='proceed']):has(button[data-action='logout'])";

/**
 * Args:
 *   request: the Playwright request fixture.
 *   method: HTTP verb.
 *   route: path below api/v1/.
 *   data: JSON body, or undefined for none.
 *
 * Returns:
 *   The APIResponse of the call, authenticated as the native administrator.
 */
function adminApi(request, method, route, data) {
  return apiFetchOnion(request, `${appBaseUrl}/api/v1/${route}`, {
    method,
    headers: { "Espo-Authorization": Buffer.from(`${adminUsername}:${adminNativePassword}`).toString("base64") },
    data,
    timeout: resolveTimeout(30_000),
  });
}

/**
 * Args:
 *   page: a page on the EspoCRM sign-in form.
 *
 * Returns:
 *   A promise of the App/user response the sign-in answers with.
 */
function appUserResponse(page) {
  return page.waitForResponse(
    (response) => response.url().includes("/api/v1/App/user") && response.request().method() === "GET",
    { timeout: resolveTimeout(60_000) },
  );
}

test("2fa enrollment: with its own second factor enforced EspoCRM sends a regular account without one to setup before it gets in", async ({ page, request }) => {
  skipUnlessServiceDisabled("sso");
  skipUnlessServiceDisabled("ldap");
  skipUnlessServiceDisabled("recaptcha");
  test.skip(!nativeEnabled, "LOGIN_METHOD_NATIVE_ENABLED=false");
  test.skip(!twoFactorEnabled, "LOGIN_METHOD_2FA_ENABLED=false");
  test.setTimeout(resolveTimeout(240_000));
  expect(adminNativePassword, "ADMIN_NATIVE_PASSWORD must be set while LDAP is off").toBeTruthy();

  const settings = await adminApi(request, "GET", "Settings");
  expect(settings.status(), "the administrator must read the EspoCRM settings").toBe(200);
  const { auth2FA, auth2FAForced } = await settings.json();
  expect(auth2FA, "login.method.2fa is on, so EspoCRM must offer its own second factor").toBe(true);

  const suffix = `${Date.now().toString(36)}${crypto.randomBytes(3).toString("hex")}`;
  const probe = { userName: `infinito-2fa-probe-${suffix}`, password: crypto.randomBytes(24).toString("base64url") };
  let probeId = null;
  let forcing = false;
  try {
    const created = await adminApi(request, "POST", "User", {
      userName: probe.userName,
      password: probe.password,
      firstName: "Infinito",
      lastName: "2FA probe",
      type: "regular",
      isActive: true,
    });
    expect(created.status(), "the administrator must create the regular probe account").toBe(200);
    probeId = (await created.json()).id;
    const forced = await adminApi(request, "PUT", "Settings", { auth2FAForced: true });
    expect(forced.status(), "the administrator must force regular users to set up 2FA").toBe(200);
    forcing = true;

    await page.context().clearCookies();
    await gotoOnion(page, `${appBaseUrl}/`);
    const passwordField = page.locator("#field-password");
    await expect(passwordField, "EspoCRM must render its own sign-in form").toBeEditable({ timeout: resolveTimeout(60_000) });
    await page.locator("#field-userName").fill(probe.userName);
    await passwordField.fill(probe.password);
    const signIn = appUserResponse(page);
    await page.locator("#btn-login").click({ timeout: resolveTimeout(30_000) });
    const appUser = await signIn;
    expect(appUser.status(), "the password of the probe must be accepted").toBe(200);
    expect(
      (await appUser.json()).appParams?.auth2FARequired,
      "EspoCRM must flag the session of a regular account without a second factor as auth2FARequired",
    ).toBe(true);
    await expect(
      page.locator(REQUIRED_MODAL),
      "the forced setup dialog must block the application before the account gets in",
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const again = appUserResponse(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    expect((await (await again).json()).appParams?.auth2FARequired, "a reload must keep the setup requirement").toBe(true);
    await expect(page.locator(REQUIRED_MODAL), "a reload must bring the forced setup dialog back").toBeVisible({
      timeout: resolveTimeout(60_000),
    });

    await page.locator(`${REQUIRED_MODAL} button[data-action='logout']`).click({ timeout: resolveTimeout(30_000) });
    await expect(page.locator("#field-userName"), "logging out of the setup dialog must end on the sign-in form").toBeVisible({
      timeout: resolveTimeout(60_000),
    });
  } finally {
    if (forcing) {
      const restored = await adminApi(request, "PUT", "Settings", { auth2FAForced }).then(
        (response) => response.status(),
        (error) => String(error),
      );
      if (restored !== 200) {
        console.warn(`restoring auth2FAForced failed: ${restored}`);
      }
    }
    if (probeId !== null) {
      await adminApi(request, "DELETE", `User/${probeId}`).catch((error) => console.warn(`deleting the probe account failed: ${error}`));
    }
  }
});
