// @ts-check
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuoted,
  gotoOnion,
  normalizeBaseUrl,
  safeIsEnabled,
} = require("./personas");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const biberUsername = decodeDotenvQuoted(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuoted(process.env.BIBER_PASSWORD);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  test.skip(safeIsEnabled("sso"), "SSO is enabled — templates/env.j2 selects saml, not ldap");
  test.skip(!safeIsEnabled("ldap"), "LDAP is disabled — AUTH_TYPE is native here");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
});

/** Sign in through SuiteCRM's own login view and return its session state. */
async function formLogin(page, username, password) {
  const landing = await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  expect(landing, "the app must answer the initial navigation").toBeTruthy();
  expect(landing.status(), "the login view must render, not error").toBeLessThan(400);

  const usernameField = page.locator("input[name='username']").first();
  await usernameField.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  await usernameField.fill(username);
  await page.locator("input[type='password']").first().fill(password);

  const loggedIn = page.waitForResponse(
    (response) => response.url().includes("/login") && response.request().method() === "POST",
    { timeout: resolveTimeout(120_000) },
  );
  await page.locator("#login-button").click({ timeout: resolveTimeout(30_000) });
  const login = await loggedIn;

  const response = await page.request.get(`${appBaseUrl}/session-status`, {
    timeout: resolveTimeout(30_000),
  });
  expect(response.status(), "session-status must answer").toBeLessThan(400);
  return { login, status: await response.json() };
}

test("biber: the directory account signs in and is created from the directory entry", async ({ page }) => {
  const { login, status } = await formLogin(page, biberUsername, biberPassword);

  expect(login.status(), "the directory bind must be accepted").toBeLessThan(400);
  expect(
    status.active,
    "LDAP_AUTO_CREATE must mint the account from the bind and leave a session behind",
  ).toBe(true);
  expect(status.userName).toBe(biberUsername);
});

test("administrator: the directory account signs in", async ({ page }) => {
  const { login, status } = await formLogin(page, adminUsername, adminPassword);

  expect(login.status(), "the directory bind must be accepted").toBeLessThan(400);
  expect(status.active, "the administrator must reach an authenticated session").toBe(true);
  expect(status.userName).toBe(adminUsername);
});
