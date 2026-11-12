const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const shared = require("../_shared");

test("addon integration-for-listmonk-mailing-list-and-newsletter-manager: the newsletter plugin is active and a distinct Listmonk partner is resolved", async ({ browser }) => {
  skipUnlessAddonEnabled("integration-for-listmonk-mailing-list-and-newsletter-manager");
  skipUnlessServiceEnabled("sso");
  test.setTimeout(resolveTimeout(120_000));

  const partnerBaseUrl = (shared.env.listmonkBaseUrl || "").trim();
  expect(
    /^https?:\/\//i.test(partnerBaseUrl),
    "LISTMONK_BASE_URL must resolve to the deployed partner Listmonk base URL when the addon is enabled — it is the same url.base the addon's api_url is built from, so an empty value means subscriptions have nowhere to go"
  ).toBeTruthy();

  const wpHost = new URL(shared.env.wpBaseUrl).host;
  const partnerHost = new URL(partnerBaseUrl).host;
  expect(
    partnerHost,
    "the Listmonk partner host must be distinct from the WordPress host"
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

    const row = page
      .locator('tr[data-slug="integration-for-listmonk-mailing-list-and-newsletter-manager"]')
      .first();
    await expect(
      row,
      "wp-admin must list the Listmonk integration plugin row — its absence means the install step never landed the addon"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(
      row,
      "the plugin row must offer Deactivate, which only an ACTIVE plugin does; a downloaded-but-inactive plugin never posts a subscription to Listmonk"
    ).toContainText(/deactivate/i, { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
