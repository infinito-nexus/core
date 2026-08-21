const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const {
  resolveTimeout,
  isOnionTarget,
  isSplitRealmOidc,
} = require("../timeouts");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon infinito-http-onion-socks: server-side OIDC against an onion issuer completes", async ({
  browser,
}) => {
  skipUnlessAddonEnabled("infinito-http-onion-socks");
  skipUnlessServiceEnabled("sso");
  test.skip(
    !isOnionTarget() && !isSplitRealmOidc(),
    "the SOCKS route only applies when the OIDC issuer is a .onion"
  );
  test.setTimeout(resolveTimeout(180_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await gotoOnion(
      page,
      `${shared.env.wpBaseUrl}/wp-admin/plugins.php?plugin_status=mustuse`,
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );

    await expect(
      page.locator("#the-list"),
      "the Must-Use plugins screen must list the onion-SOCKS mu-plugin under the Plugin Name its header declares — one absent from this screen was never copied into wp-content/mu-plugins"
    ).toContainText("Infinito.Nexus HTTP Onion SOCKS", {
      timeout: resolveTimeout(30_000),
    });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
