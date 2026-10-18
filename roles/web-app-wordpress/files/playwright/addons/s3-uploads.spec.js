const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { resolveTimeout } = require("../timeouts");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon s3-uploads: the S3 Uploads plugin is installed and active", async ({ browser }) => {
  skipUnlessAddonEnabled("s3-uploads");
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

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/plugins.php?plugin_status=active`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    await expect(
      page.locator("#the-list"),
      "the active-plugins screen must list S3 Uploads under the Plugin Name its header declares; the release asset carries no top-level folder, so a plugin missing here was unpacked under the wrong slug"
    ).toContainText("S3 Uploads", { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
