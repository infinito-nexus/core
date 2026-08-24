const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// `user_ldap` is the LDAP auth-path plugin (backs the native credential form
// with the directory). It has no distinct in-app page; the deterministic
// browser-reachable proof that LDAP federation is live is that the LDAP-only
// `biber` persona — who has no local Nextcloud account — can authenticate and
// land on an authenticated shell. Reuse the shared LDAP-first-login retry flow
// rather than reimplementing LDAP mechanics. This is only meaningful in the
// native+LDAP variant (no Keycloak handoff); the OIDC flavors are covered by
// the OIDC addon specs, so skip when OIDC owns the login journey.
test("addon user_ldap: biber authenticates via LDAP-backed native login", async ({ browser }) => {
  skipUnlessAddonEnabled("user_ldap");
  skipUnlessServiceEnabled("ldap");

  test.skip(
    shared.env.nextcloudOidcEnabled,
    "user_ldap native-login proof is only meaningful when OIDC is off; the OIDC flavors authenticate biber through Keycloak and are covered by the OIDC addon specs.",
  );

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloudWithRetry(
      page,
      shared.env.biberUsername,
      shared.env.biberPassword,
    );

    const shellState = await shared.waitForVisibleCandidate(
      page,
      shared.getNextcloudShellCandidates(page),
      resolveTimeout(60_000),
      "Timed out waiting for an authenticated Nextcloud shell after the biber LDAP login flow",
    );
    await expect(shellState.locator).toBeVisible();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
