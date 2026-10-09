const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon video-manager-for-peertube: the video manager is active and a distinct PeerTube partner is resolved", async ({ browser }) => {
  skipUnlessAddonEnabled("video-manager-for-peertube");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const partnerBaseUrl = (shared.env.peertubeBaseUrl || "").trim();
  expect(
    /^https?:\/\//i.test(partnerBaseUrl),
    "PEERTUBE_BASE_URL must resolve to the deployed partner PeerTube base URL when the addon is enabled — it is the same url.base the addon's instance_url carries, so an empty value means there is no instance to list videos from"
  ).toBeTruthy();

  const wpHost = new URL(shared.env.wpBaseUrl).host;
  const partnerHost = new URL(partnerBaseUrl).host;
  expect(
    partnerHost,
    "the PeerTube partner host must be distinct from the WordPress host"
  ).not.toBe(wpHost);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/plugins.php`, {
      waitUntil: "domcontentloaded",
      timeout: resolveTimeout(60_000),
    });

    const row = page.locator('tr[data-slug="video-manager-for-peertube"]').first();
    await expect(
      row,
      "wp-admin must list the video-manager-for-peertube plugin row — its absence means the install step never landed the addon"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      row,
      "the plugin row must offer Deactivate, which only an ACTIVE plugin does; a downloaded-but-inactive plugin embeds no PeerTube video"
    ).toContainText(/deactivate/i, { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
