const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("integration integration_peertube: connects Nextcloud to the partner PeerTube via provisioned OAuth", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_peertube");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const peertubePanel = page
      .locator("#peertube_prefs, #peertube, #peertube-content")
      .first();
    await expect(
      peertubePanel,
      "the PeerTube integration admin panel must render when integration_peertube is enabled — its absence means the app failed to install/configure and the coupling never landed"
    ).toBeVisible({ timeout: 60_000 });

    const instancesField = peertubePanel
      .locator("#peertube-instances")
      .or(peertubePanel.locator("textarea"))
      .first();
    await expect(
      instancesField,
      "the PeerTube admin panel must expose the allowed-instances field"
    ).toBeVisible({ timeout: 30_000 });

    const configuredInstances = ((await instancesField.inputValue().catch(() => "")) || "").trim();
    const firstInstance = configuredInstances
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .find((s) => /^https?:\/\//i.test(s));
    expect(
      firstInstance,
      "the PeerTube admin instances field must be populated with an absolute partner URL (addon hook sets the `instances` app value)"
    ).toBeTruthy();

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const instanceHost = new URL(firstInstance).host;
    expect(
      instanceHost,
      "the configured PeerTube instance must be the partner instance, not Nextcloud itself"
    ).not.toBe(nextcloudHost);

    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const connect = page
      .getByRole("button", { name: /connect to peertube/i })
      .or(page.getByRole("link", { name: /connect to peertube/i }))
      .first();
    await expect(
      connect,
      "the 'Connect to PeerTube' control must render once the partner instance is provisioned — its absence means the per-user OAuth bridge never wired up"
    ).toBeVisible({ timeout: 60_000 });

    const popupPromise = page.waitForEvent("popup", { timeout: 15_000 }).catch(() => null);
    await Promise.all([
      page.waitForEvent("framenavigated", { timeout: 60_000 }).catch(() => {}),
      connect.click(),
    ]);

    const popup = await popupPromise;
    const currentUrl = () => (popup ? popup.url() : page.url());

    await expect
      .poll(currentUrl, { timeout: 60_000 })
      .toMatch(/[?&]response_type=code\b/i);

    const authorizeUrl = new URL(currentUrl());
    expect(
      authorizeUrl.host,
      "PeerTube OAuth authorize must be served by the partner instance, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorizeUrl.host,
      "PeerTube OAuth authorize host must match the configured partner instance"
    ).toBe(instanceHost);
    expect(
      authorizeUrl.searchParams.get("client_id"),
      "the authorize redirect must carry the provisioned PeerTube OAuth client_id"
    ).toBeTruthy();
    expect(authorizeUrl.searchParams.get("response_type")).toBe("code");

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
