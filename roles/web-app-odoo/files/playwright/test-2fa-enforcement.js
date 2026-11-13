const { test, expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");
const { skipUnlessServiceDisabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { baseUrl, nativeLoginToOdoo, submitAdminPassword, twoFactorEnforced } = require("./_shared");

const WEB_CLIENT = ".o_web_client, .o_action_manager";
const MAILED_CODE = 'form input[name="totp_token"]';

test("2fa: with its own second factor enforced Odoo holds the administrator's password sign-in at the mailed code", async ({ page }) => {
  test.skip(!twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=false");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();

  await submitAdminPassword(page, baseUrl());
  await expect(page, "the password must end on the second-factor step").toHaveURL(/\/web\/login\/totp/, {
    timeout: resolveTimeout(60_000),
  });
  await expect(page.locator(MAILED_CODE), "Odoo must ask for the code it mailed").toBeVisible({ timeout: resolveTimeout(60_000) });

  await gotoOnion(page, `${baseUrl()}/odoo`, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  await expect(page, "without the code /odoo must send the administrator back to the sign-in").toHaveURL(/\/web\/login/, {
    timeout: resolveTimeout(60_000),
  });
  await expect(page.locator(WEB_CLIENT), "without the code Odoo must render no web client").toHaveCount(0);
});

test("2fa: with the enforcement off Odoo lets the administrator's password sign-in into the web client", async ({ page }) => {
  skipUnlessServiceDisabled("sso");
  test.skip(twoFactorEnforced, "LOGIN_METHOD_2FA_ENFORCED=true");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();

  await nativeLoginToOdoo(page, baseUrl(), page.locator(WEB_CLIENT).first());
  await expect(page, "without the enforcement the sign-in must leave the login pages").not.toHaveURL(/\/web\/login/);
});
