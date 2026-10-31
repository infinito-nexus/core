const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon video-conferencing-with-bbb: the conferencing plugin is active and a distinct BigBlueButton partner is resolved", async ({ browser }) => {
  skipUnlessAddonEnabled("video-conferencing-with-bbb");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const partnerBaseUrl = (shared.env.bigbluebuttonBaseUrl || "").trim();
  expect(
    /^https?:\/\//i.test(partnerBaseUrl),
    "BIGBLUEBUTTON_BASE_URL must resolve to the deployed partner BigBlueButton base URL when the addon is enabled — it is the same url.base the addon's api_url is built from, so an empty value means the bridge has no partner to reach"
  ).toBeTruthy();

  const wpHost = new URL(shared.env.wpBaseUrl).host;
  const partnerHost = new URL(partnerBaseUrl).host;
  expect(
    partnerHost,
    "the BigBlueButton partner host must be distinct from the WordPress host"
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

    const row = page.locator('tr[data-slug="video-conferencing-with-bbb"]').first();
    await expect(
      row,
      "wp-admin must list the video-conferencing-with-bbb plugin row — its absence means the install step never landed the addon"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      row,
      "the plugin row must offer Deactivate, which only an ACTIVE plugin does; a downloaded-but-inactive plugin adds no conferencing surface"
    ).toContainText(/deactivate/i, { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
