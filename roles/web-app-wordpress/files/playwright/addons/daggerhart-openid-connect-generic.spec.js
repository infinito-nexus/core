const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

// daggerhart-openid-connect-generic is WordPress's OIDC login plugin: it
// has no dedicated user-facing page. Its observable surface is that the
// role's existing administrator OIDC login idiom (wpAdminLoginViaOidc →
// Keycloak round-trip → wp-admin) succeeds. We REUSE that idiom rather
// than reimplement OIDC mechanics, gating behind the addon flag and the
// sso service.
test("addon daggerhart-openid-connect-generic: administrator OIDC login lands in wp-admin", async ({ browser }) => {
  skipUnlessAddonEnabled("daggerhart-openid-connect-generic");
  skipUnlessServiceEnabled("sso");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await expect(page, "Expected to land in wp-admin after the OIDC round-trip").toHaveURL(
      /\/wp-admin\/?/,
      { timeout: resolveTimeout(30_000) }
    );
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
