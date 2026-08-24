const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// `user_oidc` is the OIDC auth-path plugin selected when sso_oidc_plugin ==
// "user_oidc". Like the other OIDC plugins it has no distinct in-app page; its
// only browser-reachable surface is the login journey. Reuse the shared
// `loginToStandaloneNextcloud` flow (which handles the Keycloak handoff for
// every OIDC flavor) instead of reimplementing OIDC mechanics, and assert that
// an authenticated Nextcloud shell results.
test("addon user_oidc: nextcloud OIDC login surface authenticates", async ({ browser }) => {
  skipUnlessAddonEnabled("user_oidc");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for an authenticated Nextcloud shell after the user_oidc OIDC login flow",
    );
    await expect(shellState.locator).toBeVisible();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
