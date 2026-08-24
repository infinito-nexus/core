const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// `oidc_login` (pulsejet/nextcloud-oidc-login) is the OIDC auth-path plugin
// selected when sso_oidc_plugin == "oidc_login" (the OIDC+LDAP flavor, which
// auto-redirects /login straight to Keycloak). It has no distinct in-app page;
// its only browser-reachable surface is the login journey. The shared
// `loginToStandaloneNextcloud` flow already handles the auto_redirect /
// alt-login button shapes for this flavor, so we reuse it rather than
// reimplementing OIDC mechanics, and assert an authenticated shell results.
test("addon oidc_login: nextcloud OIDC login surface authenticates", async ({ browser }) => {
  skipUnlessAddonEnabled("oidc_login");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for an authenticated Nextcloud shell after the oidc_login OIDC login flow",
    );
    await expect(shellState.locator).toBeVisible();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
