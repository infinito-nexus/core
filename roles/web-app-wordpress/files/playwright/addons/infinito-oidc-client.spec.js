const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("administrator: addon infinito-oidc-client: the container-served client signs the administrator in and nobody opens its settings page", async ({ browser }) => {
  skipUnlessAddonEnabled("infinito-oidc-client");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  try {
    await shared.wpAdminLoginViaOidc(page, shared.env.wpBaseUrl, shared.env.adminUsername, shared.env.adminPassword);
    await expect(page.locator("#adminmenu"), "the container-served client MUST sign the administrator in").toBeVisible({
      timeout: resolveTimeout(30_000),
    });
    await expect(
      page.locator("#adminmenu a[href*='page=openid-connect-generic-settings']"),
      "the admin menu MUST NOT offer the SSO settings, which come from the deployment"
    ).toHaveCount(0);
    const response = await gotoOnion(
      page,
      `${shared.env.wpBaseUrl}/wp-admin/options-general.php?page=openid-connect-generic-settings`,
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    expect(response && response.status(), "the SSO settings page MUST answer 403 to the administrator too").toBe(403);
    await shared.wpSignOut(page, shared.env.wpBaseUrl);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
