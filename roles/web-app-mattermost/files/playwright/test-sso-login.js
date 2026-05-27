const { test, expect } = require("@playwright/test");

const { performKeycloakLoginForm } = require("./personas");

exports.register = function (shared) {
  test("mattermost: sso login, verify channel view, logout", async ({ page }) => {
    test.skip(!shared.oidcEnabled, "OIDC shared service disabled");

    const oidcAuthUrl = shared.expectedOidcAuthUrl();
    const baseUrl = shared.expectedMattermostBaseUrl();

    await shared.startMattermostSsoFlow(page, baseUrl);

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: `Expected redirect to Keycloak OIDC: ${oidcAuthUrl}`,
      })
      .toContain(oidcAuthUrl);

    await performKeycloakLoginForm(page, shared.env.adminUsername, shared.env.adminPassword);

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: `Expected redirect back to Mattermost: ${baseUrl}`,
      })
      .toContain(baseUrl);

    await shared.dismissMattermostPopups(page);
    await shared.waitForMattermostChannelView(page, 30_000);
    await shared.mattermostLogout(page, baseUrl);

    // Mattermost v11+ defaults to /landing#/ rather than /login for unauthenticated requests.
    await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.url(), {
        timeout: 15_000,
        message: "Expected Mattermost to redirect to /login or /landing after logout",
      })
      .toMatch(/\/(login|landing)/);
  });
};
