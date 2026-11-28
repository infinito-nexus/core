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

test("administrator: the password grant of the admin API follows the native method while SSO is on", async ({ request }) => {
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

  if (!nativeEnabled) {
    expect(grant.status(), "denyPasswordLogin must refuse the password grant while the native method is off").toBe(400);
    const refusal = (await grant.json()).errors?.[0]?.title || "";
    expect(refusal, "the refusal must name the unsupported grant, not a wrong password").toMatch(
      /grant type is not supported/i,
    );
    return;
  }

  expect(grant.status(), "the password grant must stay open while the native method is on").toBe(200);
  const token = (await grant.json()).access_token;
  expect(token, "the password grant must return an access token").toBeTruthy();

  const info = await apiFetchOnion(request, `${base}/api/_info/version`, {
    method: "GET",
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    timeout: resolveTimeout(60_000),
  });
  expect(info.status(), "the password grant's token must authorize the admin API").toBe(200);
});
