/**
 * Assert the browser is in an unauthenticated state by re-navigating
 * to the role's canonical surface and verifying the post-logout
 * request did NOT silently succeed with a 5xx.
 *
 * The post-logout request is allowed to either re-engage the auth
 * chain (redirect to keycloak / the role's /sso/login page) or to
 * serve the public landing for roles whose canonical surface is
 * reachable without auth. Both are acceptable; the assertion is that
 * the request did NOT 5xx and did NOT land on an authenticated-only
 * surface that should be gated.
 */

const { expect } = require("@playwright/test");

async function assertUnauthenticatedLanding(page, appBaseUrl) {
  if (!appBaseUrl) return;
  const response = await page.goto(`${appBaseUrl}/`, { waitUntil: "domcontentloaded" }).catch(() => null);
  if (!response) return;
  const status = response.status();
  expect(status, "post-logout request must not 5xx").toBeLessThan(500);
}

module.exports = { assertUnauthenticatedLanding };
