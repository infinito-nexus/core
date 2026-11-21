const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { isServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.JENKINS_BASE_URL || "").replace(/\/$/, "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME);
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD);

/**
 * Authenticate one account against whichever security realm the current
 * variant selected, without asserting what the account may see afterwards.
 *
 * Args:
 *   page: the Playwright page to drive.
 *   username: the account's login name.
 *   password: the account's password.
 */
async function loginAs(page, username, password) {
  expect(baseUrl, "JENKINS_BASE_URL must be set").toBeTruthy();
  expect(username, "the login name must be set").toBeTruthy();
  expect(password, "the password must be set").toBeTruthy();

  if (isServiceEnabled("sso")) {
    await gotoOnion(page, `${baseUrl}/`);
    await performKeycloakLoginForm(page, username, password);
  } else {
    await gotoOnion(page, `${baseUrl}/login`);
    const user = page.locator("input[name='j_username']").first();
    await expect(user).toBeVisible({ timeout: resolveTimeout(60_000) });
    await user.fill(username);
    await page.locator("input[name='j_password']").first().fill(password);
    await page
      .locator("button[name='Submit'], input[type='submit']")
      .first()
      .click({ timeout: resolveTimeout(30_000) });
  }

  await expect
    .poll(async () => (await whoAmI(page)).name, {
      timeout: resolveTimeout(60_000),
      message: `Expected Jenkins to report ${username} as the current user after login`,
    })
    .toBe(username);
}

/**
 * Return the controller's view of the current session from /whoAmI, which
 * Jenkins serves without the Overall/Read permission.
 *
 * Args:
 *   page: a Playwright page whose context carries the Jenkins session.
 */
async function whoAmI(page) {
  const response = await page.request.get(`${baseUrl}/whoAmI/api/json`, {
    failOnStatusCode: false,
    timeout: resolveTimeout(30_000),
  });
  if (!response.ok()) return { name: "", authorities: [] };
  return response.json();
}

/**
 * Authenticate as the administrator against whichever security realm the
 * current variant selected.
 *
 * Args:
 *   page: the Playwright page to drive.
 */
async function loginAsAdministrator(page) {
  await loginAs(page, adminUsername, adminPassword);

  const landing = await gotoOnion(page, `${baseUrl}/`);
  expect(
    landing.status(),
    "Jenkins must serve its dashboard to the administrator; 403 means the session never authenticated",
  ).toBeLessThan(400);
  await expect(page.locator(`a[href$='/user/${adminUsername}']`).first()).toBeVisible({
    timeout: resolveTimeout(60_000),
  });
}

/**
 * Return the plugin manager's record for one plugin short name.
 *
 * Args:
 *   page: an authenticated Playwright page.
 *   shortName: the Jenkins plugin artifact id.
 */
async function fetchPluginRecord(page, shortName) {
  const response = await page.request.get(`${baseUrl}/pluginManager/api/json?depth=1`, {
    timeout: resolveTimeout(60_000),
  });
  expect(
    response.status(),
    `the plugin manager API must answer for ${shortName}`,
  ).toBeLessThan(400);
  const payload = await response.json();
  return (payload.plugins || []).find((plugin) => plugin.shortName === shortName);
}

module.exports = { baseUrl, fetchPluginRecord, loginAs, loginAsAdministrator, whoAmI };
