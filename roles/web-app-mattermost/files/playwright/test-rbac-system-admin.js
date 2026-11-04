const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { performKeycloakLoginForm } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");

async function signInThroughKeycloak(page, shared, username, password) {
  const baseUrl = shared.expectedMattermostBaseUrl();
  await shared.startMattermostSsoFlow(page, baseUrl);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: "Expected the redirect to Keycloak" })
    .toContain(shared.expectedOidcAuthUrl());
  await performKeycloakLoginForm(page, username, password);
  await expect
    .poll(() => page.url(), { timeout: resolveTimeout(60_000), message: `Expected the redirect back to ${baseUrl}` })
    .toContain(baseUrl);
  await shared.dismissMattermostPopups(page);
}

async function ownSystemRoles(page, shared) {
  const root = shared.expectedMattermostBaseUrl().replace(/\/$/, "");
  const response = await page.request.get(`${root}/api/v4/users/me`, {
    headers: { "X-Requested-With": "XMLHttpRequest" },
    timeout: resolveTimeout(30_000),
  });
  const body = await response.text();
  expect(response.ok(), `GET /api/v4/users/me must answer for the signed-in account, got ${response.status()}: ${body.slice(0, 300)}`).toBe(true);
  return String(JSON.parse(body).roles || "").split(/\s+/);
}

exports.register = function (shared) {
  test("rbac: the administrator keeps the Mattermost system_admin role after the deploy-time reconcile", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await signInThroughKeycloak(page, shared, shared.env.adminUsername, shared.env.adminPassword);
    expect(await ownSystemRoles(page, shared), "the platform administrator must stay a Mattermost system admin").toContain("system_admin");
    await shared.mattermostLogout(page, shared.expectedMattermostBaseUrl());
  });

  test("rbac: biber without the administrator role holds no Mattermost system_admin role", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    await signInThroughKeycloak(page, shared, shared.env.biberUsername, shared.env.biberPassword);
    const roles = await ownSystemRoles(page, shared);
    expect(roles, "a realm user signs in to Mattermost as a regular member").toContain("system_user");
    expect(roles, "a realm user outside the administrator role group must not be a Mattermost system admin").not.toContain("system_admin");
    await shared.mattermostLogout(page, shared.expectedMattermostBaseUrl());
  });
};
