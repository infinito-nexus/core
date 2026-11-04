const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { decodeDotenvQuoted, gotoOnion, normalizeBaseUrl } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);
const twoFactorEnabled = process.env.LOGIN_METHOD_2FA_ENABLED === "true";

test("login methods: with sso on SuiteCRM hands a visitor to Keycloak without a local form", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  await page.context().clearCookies();
  await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: "AUTH_TYPE=saml must send an unauthenticated visitor to Keycloak instead of the SuiteCRM login view",
    })
    .toMatch(/\/protocol\/saml|\/login-actions\//);
  await expect(page.locator("#login-button"), "the SuiteCRM login view must not render").toHaveCount(0);
});

test("break-glass: the local administrator signs in at /auth while sso is on and sees no 2FA enrollment", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(180_000));
  await page.context().clearCookies();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await gotoOnion(page, `${appBaseUrl}/auth`, { waitUntil: "domcontentloaded" });

  const usernameField = page.locator("input[name='username']").first();
  await expect(usernameField, "/auth must render the native login view").toBeVisible({
    timeout: resolveTimeout(60_000),
  });
  await usernameField.fill(adminUsername);
  await page.locator("input[type='password']").first().fill(adminPassword);
  const loggedIn = page.waitForResponse(
    (response) => response.url().includes("/login") && response.request().method() === "POST",
    { timeout: resolveTimeout(120_000) },
  );
  await page.locator("#login-button").click({ timeout: resolveTimeout(30_000) });
  expect((await loggedIn).status(), "the native firewall must accept the local password").toBeLessThan(400);

  const response = await page.request.get(`${appBaseUrl}/session-status`, { timeout: resolveTimeout(30_000) });
  expect(response.status(), "session-status must answer").toBeLessThan(400);
  const status = await response.json();
  expect(status.active, "the break-glass sign-in must own a SuiteCRM session").toBe(true);
  expect(status.userName, "the session must belong to the local administrator").toBe(adminUsername);

  if (!twoFactorEnabled) {
    await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "load" });
    await expect(
      page.locator("html[data-infinito-2fa-enrollment='hidden']"),
      "the javascript service must inject the enrollment hider while login.method.2fa is off",
    ).toBeAttached({ timeout: resolveTimeout(60_000) });
    await expect(
      page.locator("scrm-2fa:visible, #two-factor:visible"),
      "login.method.2fa is off, so SuiteCRM's two-factor enrollment view must stay hidden",
    ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  }
  await page.context().clearCookies();
});
