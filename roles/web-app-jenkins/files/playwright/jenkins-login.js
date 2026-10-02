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
 * Authenticate as the administrator against whichever security realm the
 * current variant selected.
 *
 * Args:
 *   page: the Playwright page to drive.
 */
async function loginAsAdministrator(page) {
  expect(baseUrl, "JENKINS_BASE_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();

  if (isServiceEnabled("sso")) {
    await gotoOnion(page, `${baseUrl}/`);
    await performKeycloakLoginForm(page, adminUsername, adminPassword);
  } else {
    await gotoOnion(page, `${baseUrl}/login`);
    const user = page.locator("input[name='j_username']").first();
    await expect(user).toBeVisible({ timeout: resolveTimeout(60_000) });
    await user.fill(adminUsername);
    await page.locator("input[name='j_password']").first().fill(adminPassword);
    await page
      .locator("button[name='Submit'], input[type='submit']")
      .first()
      .click({ timeout: resolveTimeout(30_000) });
  }

  await expect(page.locator("body")).toBeVisible({ timeout: resolveTimeout(60_000) });
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

module.exports = { baseUrl, fetchPluginRecord, loginAsAdministrator };
