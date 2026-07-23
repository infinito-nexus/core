const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// `sociallogin` is the OIDC auth-path plugin selected when sso_oidc_plugin ==
// "sociallogin" (OIDC-only flavor). It is not a distinct in-app page: its only
// browser-reachable surface is the login journey itself. The shared
// `loginToStandaloneNextcloud` flow already knows the "sociallogin" flavor (it
// clicks the "Log in with Keycloak" entry before the credential form), so we
// reuse it rather than reimplementing OIDC mechanics, and assert that an
// authenticated Nextcloud shell results.
test("addon sociallogin: nextcloud OIDC login surface authenticates", async ({ browser }) => {
  skipUnlessAddonEnabled("sociallogin");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for an authenticated Nextcloud shell after the sociallogin OIDC login flow",
    );
    await expect(shellState.locator).toBeVisible();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
