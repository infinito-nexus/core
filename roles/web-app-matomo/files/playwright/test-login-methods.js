const { test, expect } = require("@playwright/test");

const { BREAKGLASS_LOGIN_PATH, LOGIN_FIELD, appBaseUrl, nativeLoginEnabled, oidcButtonSelector } = require("./_shared");
const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

test("guest: with SSO on the Matomo login offers the Keycloak entry and no disabled method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await gotoOnion(page, `${appBaseUrl}/index.php?module=Login`);

  await expect(
    page.locator(oidcButtonSelector()).first(),
    "the Keycloak entry must render on the Matomo login page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (!nativeLoginEnabled) {
    for (const selector of [LOGIN_FIELD, "input#login_form_password", "#login_form_submit", "#login_form_nav"]) {
      await expect(page.locator(selector).first(), `${selector} must stay hidden while the native method is off`).toBeHidden({
        timeout: resolveTimeout(10_000),
      });
    }
  }
});

test("guest: the break-glass login URL keeps the password form while SSO is on", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await gotoOnion(page, `${appBaseUrl}${BREAKGLASS_LOGIN_PATH}`);

  await expect(
    page.locator(LOGIN_FIELD).first(),
    "the superuser's break-glass form must render behind fallback=local",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
});
