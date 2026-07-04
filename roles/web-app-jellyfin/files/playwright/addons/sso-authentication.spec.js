const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

test("addon sso-authentication: biber signs in via the SSO/OIDC plugin and lands on the Jellyfin home", async ({ page }) => {
  skipUnlessAddonEnabled("sso-authentication");
  test.setTimeout(90_000);
  expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();
  expect(shared.env.oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();

  await shared.signInViaOidc(page, shared.env.biberUsername, shared.env.biberPassword, "biber-oidc");
  await expect(page.locator("body")).toContainText(/home|library|media|jellyfin/i, { timeout: 60_000 });
  await shared.logout(page, "biber-oidc");
});
