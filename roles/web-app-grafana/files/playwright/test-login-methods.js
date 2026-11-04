const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, gotoOnion } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const registrationEnabled = process.env.LOGIN_METHOD_REGISTRATION_ENABLED === "true";
const breakglassUsername = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_USERNAME);
const breakglassPassword = decodeDotenvQuotedValue(process.env.ADMIN_NATIVE_PASSWORD);

test("login methods: with sso on the sign-in page offers Keycloak and no disabled entry", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));
  await page.context().clearCookies();
  await gotoOnion(page, `${shared.env.appBaseUrl}/login?disableAutoLogin=true`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("a[href*='login/generic_oauth']").first(),
    "the sign-in page must offer the Keycloak entry",
  ).toBeVisible({ timeout: resolveTimeout(60_000) });

  const passwordField = page.locator("input[name='password']");
  if (nativeEnabled) {
    await expect(passwordField, "login.method.native is on, so the local form must render").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  } else {
    await expect(passwordField, "GF_AUTH_DISABLE_LOGIN_FORM must remove the local form").toHaveCount(0);
  }

  const signUp = page.locator("a[href$='signup']");
  if (registrationEnabled) {
    await expect(signUp.first(), "login.method.registration is on, so the sign-up entry must render").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
  } else {
    await expect(signUp, "GF_USERS_ALLOW_SIGN_UP=false must remove the sign-up entry").toHaveCount(0);
  }
});

test("break-glass: the local administrator authenticates against the HTTP API while sso is on", async ({ request }) => {
  skipUnlessServiceEnabled("sso");
  expect(breakglassUsername, "ADMIN_NATIVE_USERNAME must be set").toBeTruthy();
  expect(breakglassPassword, "ADMIN_NATIVE_PASSWORD must be set").toBeTruthy();
  const credentials = Buffer.from(`${breakglassUsername}:${breakglassPassword}`).toString("base64");
  const response = await request.get(`${shared.env.appBaseUrl}/api/user`, {
    headers: { Authorization: `Basic ${credentials}` },
    failOnStatusCode: false,
    timeout: resolveTimeout(60_000),
  });
  expect(response.status(), `basic auth of the break-glass account must pass: ${await response.text()}`).toBe(200);
  const user = await response.json();
  expect(user.login, "the API must answer for the break-glass account").toBe(breakglassUsername);
  expect(user.isGrafanaAdmin, "the break-glass account must keep the Grafana server admin flag").toBe(true);
});
