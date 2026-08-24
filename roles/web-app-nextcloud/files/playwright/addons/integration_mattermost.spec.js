const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

// Full-coupling check for nextcloud/integration_mattermost.
//
// The addon hook (tasks/addons/integration_mattermost_provision.yml) registers an
// OAuth 2.0 application on the partner Mattermost and persists oauth_instance_url +
// client_id + client_secret into the app. This spec proves the coupling behaviourally:
//
//   1) the integration_mattermost app is enabled (admin app-detail "Disable"),
//   2) the personal "Connected accounts" page exposes the Mattermost connect control,
//   3) clicking connect performs the OAuth authorize redirect to the PARTNER Mattermost
//      host (not Nextcloud) carrying the provisioned client_id and response_type=code —
//      which can only happen once the hook persisted client_id + oauth_instance_url. A
//      missing coupling would keep the browser on Nextcloud.
//
// The partner bounces the unauthenticated request through /login?redirect_to=<authorize>,
// so the authorize URL can be percent-encoded in the landing URL — decode before matching.
test("integration integration_mattermost: OAuth client provisioned and connects to Mattermost", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_mattermost");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;

  try {
    await shared.loginToStandaloneNextcloud(page);

    // 1) App is installed AND enabled.
    await gotoOnion(page,
      new URL("settings/apps/installed/integration_mattermost", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});
    await page.waitForLoadState("networkidle").catch(() => {});

    await expect(
      page.getByRole("button", { name: /^disable$/i }).or(page.locator('input[value="Disable"]')).first(),
      "integration_mattermost must be enabled (admin app-detail Disable action)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // 2) Personal connect surface renders (only when the app is enabled).
    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});
    await page.waitForLoadState("networkidle").catch(() => {});

    const connect = page
      .locator("#mattermost-connect")
      .or(page.getByRole("button", { name: /connect to mattermost/i }))
      .or(page.getByRole("link", { name: /connect to mattermost/i }))
      .first();
    await expect(
      connect,
      "the Mattermost connect control must render on Connected accounts when the app is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    // 3) Connect performs the partner OAuth authorize redirect with the provisioned client.
    const popupPromise = page.waitForEvent("popup", { timeout: resolveTimeout(15_000) }).catch(() => null);
    await Promise.all([
      page.waitForEvent("framenavigated", { timeout: resolveTimeout(60_000) }).catch(() => {}),
      connect.click({ timeout: resolveTimeout(30_000) }),
    ]);
    const popup = await popupPromise;
    const rawUrl = () => (popup ? popup.url() : page.url());
    const landing = () => decodeURIComponent(rawUrl());

    await expect
      .poll(landing, {
        timeout: resolveTimeout(60_000),
        message: "connect must redirect to the partner Mattermost OAuth authorize endpoint",
      })
      .toMatch(/\/oauth\/authorize/i);

    const decoded = landing();
    expect(
      new URL(rawUrl()).host,
      "the OAuth authorize must be served by the partner Mattermost host, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(decoded, "the OAuth authorize must carry the provisioned Mattermost client_id").toMatch(/client_id=/i);
    expect(decoded, "the OAuth authorize must be an authorization-code-flow request").toMatch(/response_type=code/i);

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
