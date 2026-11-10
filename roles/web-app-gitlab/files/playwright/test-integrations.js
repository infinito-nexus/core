const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { gotoOnion, normalizeBaseUrl } = require("./personas");

async function expectInstanceIntegrationIsAdminOnly(page, addon, label) {
  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL || "");
  expect(appBaseUrl, "APP_BASE_URL must be set").toBeTruthy();
  await page.context().clearCookies();

  const url = `${appBaseUrl}/admin/application_settings/integrations/${addon}/edit`;
  const response = await gotoOnion(page, url, { waitUntil: "domcontentloaded" });
  expect(response, `Expected a response from ${url}`).toBeTruthy();
  expect(
    response.status(),
    `GitLab answered ${response.status()} for the ${label} instance-integration settings page, so this build does not route instance-level integrations at all`,
  ).toBeLessThan(400);
  expect(
    page.url(),
    `the ${label} instance-integration settings page must bounce an anonymous visitor to the sign-in form; serving it would expose the integration credentials of every project`,
  ).toContain("/users/sign_in");
}

function register() {
  test("integration confluence: the Confluence instance-integration page is routed and admin-only", async ({ page }) => {
    skipUnlessServiceEnabled("confluence");
    await expectInstanceIntegrationIsAdminOnly(page, "confluence", "Confluence");
  });

  test("integration jenkins: the Jenkins instance-integration page is routed and admin-only", async ({ page }) => {
    skipUnlessServiceEnabled("jenkins");
    await expectInstanceIntegrationIsAdminOnly(page, "jenkins", "Jenkins");
  });

  test("integration jira: the Jira instance-integration page is routed and admin-only", async ({ page }) => {
    skipUnlessServiceEnabled("jira");
    await expectInstanceIntegrationIsAdminOnly(page, "jira", "Jira");
  });

  test("integration matrix: the Matrix instance-integration page is routed and admin-only", async ({ page }) => {
    skipUnlessServiceEnabled("matrix");
    await expectInstanceIntegrationIsAdminOnly(page, "matrix", "Matrix");
  });

  test("integration mattermost: the Mattermost notifications instance-integration page is routed and admin-only", async ({ page }) => {
    skipUnlessServiceEnabled("mattermost");
    await expectInstanceIntegrationIsAdminOnly(page, "mattermost", "Mattermost notifications");
  });
}

module.exports = { expectInstanceIntegrationIsAdminOnly, register };
