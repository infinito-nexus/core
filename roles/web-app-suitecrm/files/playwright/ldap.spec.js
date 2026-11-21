// @ts-check
const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const {
  decodeDotenvQuoted,
  gotoOnion,
  normalizeBaseUrl,
} = require("./personas");
const { holdsAdministration } = require("./saml-login");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("./service-gating");

test.use({ ignoreHTTPSErrors: true });

const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
const biberUsername = decodeDotenvQuoted(process.env.BIBER_USERNAME);
const biberPassword = decodeDotenvQuoted(process.env.BIBER_PASSWORD);
const adminUsername = decodeDotenvQuoted(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuoted(process.env.ADMIN_PASSWORD);

test.beforeEach(async ({ page }) => {
  skipUnlessServiceEnabled("ldap");
  skipUnlessServiceDisabled("sso");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();
});

/** Sign in through SuiteCRM's own login view and return its session state. */
async function formLogin(page, username, password) {
  const loginStrings = page.waitForResponse(
    (response) =>
      response.url().includes("/api/graphql") &&
      /"operationName"\s*:\s*"appStrings"/.test(response.request().postData() || ""),
    { timeout: resolveTimeout(60_000) },
  );
  const landing = await gotoOnion(page, `${appBaseUrl}/`, { waitUntil: "domcontentloaded" });
  expect(landing, "the app must answer the initial navigation").toBeTruthy();
  expect(landing.status(), "the login view must render, not error").toBeLessThan(400);

  const usernameField = page.locator("input[name='username']").first();
  await usernameField.waitFor({ state: "visible", timeout: resolveTimeout(60_000) });
  await loginStrings;
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

test("biber: a directory account outside every role group is refused", async ({ page }) => {
  const { status } = await formLogin(page, biberUsername, biberPassword);

  expect(
    status.active,
    "LDAP_PROVIDER_FILTER and LDAP_QUERY_STRING admit only members of a declared role group, so biber must not get a session",
  ).toBe(false);
  await page.context().clearCookies();
});

test("administrator: the directory account signs in and keeps the admin flag", async ({ page }) => {
  const { login, status } = await formLogin(page, adminUsername, adminPassword);

  expect(login.status(), "the directory bind must be accepted").toBeLessThan(400);
  expect(status.active, "the administrator must reach an authenticated session").toBe(true);
  expect(status.userName).toBe(adminUsername);
  expect(
    await holdsAdministration(page, appBaseUrl),
    "the platform administrator must keep the SuiteCRM admin flag",
  ).toBe(true);
  await page.context().clearCookies();
});
