const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });
test.beforeEach(shared.beforeEach);

test("addon ldap-authentication: biber signs in via the LDAP plugin and lands on the Jellyfin home", async ({ page }) => {
  skipUnlessAddonEnabled("ldap-authentication");
  // A Jellyfin user binds to exactly one auth provider. When SSO is active the
  // sso-authentication spec owns biber's login (OIDC); the LDAP login path is
  // covered by the ldap-only matrix variant, where this spec runs.
  test.skip(
    shared.env.ssoEnabled === true,
    "SSO is active: biber is OIDC-bound; the LDAP login path runs in the ldap-only variant",
  );
  test.setTimeout(60_000);
  expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  await shared.signInViaLdap(page, shared.env.biberUsername, shared.env.biberPassword, "biber-ldap");
  await expect(page.locator("body")).toContainText(/home|library|media|jellyfin/i, { timeout: 60_000 });
  await shared.logout(page, "biber-ldap");
});
