const { test, expect } = require("@playwright/test");

const { gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const { BREAKGLASS_LOGIN_PATH, baseUrl, loginMethods, nativeLoginToOdoo } = require("./_shared");

const LOGIN_FORM = "form.oe_login_form";
const SSO_ENTRY = `${LOGIN_FORM} .o_login_auth a[href*="redirect_uri="][href*="auth_oauth%2Fsignin"]`;

test("guest: with SSO on the sign-in page offers the SSO entry and no disabled method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${baseUrl()}/web/login`, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });

  await expect(
    page.locator(SSO_ENTRY).filter({ hasText: /login with sso/i }).first(),
    "the Keycloak entry must render on the Odoo sign-in page",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (!loginMethods.native && !loginMethods.ldap) {
    for (const selector of [
      `${LOGIN_FORM} input[name="login"]`,
      `${LOGIN_FORM} input[name="password"]`,
      `${LOGIN_FORM} .oe_login_buttons > button[type="submit"]`,
      `${LOGIN_FORM} a[href^="/web/reset_password"]`,
    ]) {
      await expect(page.locator(selector).first(), `${selector} must stay hidden while the form methods are off`).toBeHidden({
        timeout: resolveTimeout(10_000),
      });
    }
  }
  if (!loginMethods.passkey) {
    await expect(page.locator(`${LOGIN_FORM} a.passkey_login_link`).first(), "the passkey entry must stay hidden").toBeHidden({
      timeout: resolveTimeout(10_000),
    });
  }
  if (!loginMethods.odooCom) {
    await expect(
      page.locator(`${LOGIN_FORM} .o_login_auth a`).filter({ hasText: /odoo\.com/i }),
      "the shipped Odoo.com provider must not render",
    ).toHaveCount(0);
  }
  if (!loginMethods.registration) {
    await expect(page.locator('a[href^="/web/signup"]'), "the signup entry must not render").toHaveCount(0);
  }
});

test("administrator: the break-glass URL signs the local administrator in through the password form while SSO is on", async ({
  page,
}) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();
  const webClient = page.locator(".o_web_client, .o_main_navbar, .o_action_manager").first();

  await gotoOnion(page, `${baseUrl()}${BREAKGLASS_LOGIN_PATH}`, { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) });
  await expect(page.locator(`${LOGIN_FORM} input[name="password"]`), "fallback=local must keep the password form").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await nativeLoginToOdoo(page, baseUrl(), webClient);
});
