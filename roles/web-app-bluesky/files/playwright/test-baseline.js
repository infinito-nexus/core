const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("baseline: bluesky web UI responds on the canonical domain", async ({ page }) => {
    // Liveness probe — passes regardless of whether the OIDC gate is
    // active. The PDS XRPC layer at api.bluesky.<domain> is exercised
    // by the OIDC scenario below (which uses the broker handoff to
    // reach social-app via Keycloak).
    const { baseUrl, canonicalDomain } = shared.env;
    const response = await page.goto(`${baseUrl}/`);
    expect(response, "Expected bluesky response").toBeTruthy();
    expect(response.status(), "Expected bluesky status < 500").toBeLessThan(500);
    expect(
      response.url().includes(canonicalDomain),
      `Expected canonical domain "${canonicalDomain}" to back the bluesky URL`,
    ).toBe(true);
  });
};
