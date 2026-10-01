const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { resolveTimeout } = require("../timeouts");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon infinito-s3-uploads: the S3 endpoint mu-plugin is loaded by WordPress", async ({
  browser,
}) => {
  skipUnlessAddonEnabled("infinito-s3-uploads");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/plugins.php?plugin_status=mustuse`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    await expect(
      page.locator("#the-list"),
      "the Must-Use plugins screen must list the S3 endpoint mu-plugin under the Plugin Name its header declares; one absent from this screen was never copied into wp-content/mu-plugins"
    ).toContainText("Infinito.Nexus S3 Uploads Endpoint", {
      timeout: resolveTimeout(30_000),
    });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
