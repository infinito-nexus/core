const { test, expect } = require("@playwright/test");

const { apiFetchOnion, decodeDotenvQuotedValue, gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const base = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const SSO_BUTTON = "a.heptacom-admin-open-auth--button";

test.use({ ignoreHTTPSErrors: true });

test("guest: with SSO on the administration login offers the Keycloak entry and no disabled method", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${base}/admin#/login`, { waitUntil: "domcontentloaded" });

  await expect(
    page.locator(SSO_BUTTON).filter({ hasText: /keycloak/i }).first(),
    "AdminOpenAuth must append the Keycloak entry to the administration login",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });
  if (!nativeEnabled) {
    for (const selector of [
      ".sw-login__content input[type='password']",
      ".sw-login__content input[name$='username']",
      ".sw-login__forgot-password-action",
    ]) {
      await expect(page.locator(selector), `${selector} must stay hidden while the native method is off`).toBeHidden({
        timeout: resolveTimeout(10_000),
      });
    }
  }
});

test("administrator: the local administrator's password grant reaches the admin API while SSO is on", async ({ request }) => {
  skipUnlessServiceEnabled("sso");
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  const grant = await apiFetchOnion(request, `${base}/api/oauth/token`, {
    method: "POST",
    headers: { Accept: "application/json" },
    data: {
      client_id: "administration",
      grant_type: "password",
      scopes: "write",
      username: adminUsername,
      password: adminPassword,
    },
    timeout: resolveTimeout(60_000),
  });
  expect(grant.status(), "the break-glass password grant must stay open while the password form is hidden").toBe(200);
  const token = (await grant.json()).access_token;
  expect(token, "the password grant must return an access token").toBeTruthy();

  const info = await apiFetchOnion(request, `${base}/api/_info/version`, {
    method: "GET",
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    timeout: resolveTimeout(60_000),
  });
  expect(info.status(), "the break-glass token must authorize the admin API").toBe(200);
});
