const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

// Full-coupling check for nextcloud/integration_mattermost.
//
// The addon hook (tasks/addons/integration_mattermost.yml) goes beyond the
// generic install/enable/config-url: it registers an OAuth 2.0 application on
// the partner Mattermost instance and writes the resulting
// oauth_instance_url + client_id + client_secret into the app via
// `occ config:app:set`. This spec proves that coupling end to end:
//
//   1) the integration_mattermost app is enabled (admin app-detail "Disable"),
//   2) the personal "Connected accounts" page exposes the Mattermost connect
//      control (only rendered when the app is enabled), and
//   3) clicking connect performs the OAuth authorize redirect to the PARTNER
//      Mattermost host (not Nextcloud) carrying a real `client_id` and
//      `response_type=code` — which can only happen once the admin OAuth client
//      provisioned by the hook is persisted. This step FAILS if the OAuth
//      coupling is missing.
test("integration integration_mattermost: OAuth client provisioned and connects to Mattermost", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_mattermost");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    // 1) App is installed AND enabled: the app-detail page resolves with a
    // "Disable" action only for an enabled app.
    await page.goto(
      new URL("settings/apps/installed/integration_mattermost", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});
    await page.waitForLoadState("networkidle").catch(() => {});

    const disableAction = page
      .getByRole("button", { name: /^disable$/i })
      .or(page.locator('input[value="Disable"]'))
      .first();
    await expect(
      disableAction,
      "integration_mattermost must be enabled (admin app-detail Disable action)"
    ).toBeVisible({ timeout: 60_000 });

    // 2) Personal connect surface renders (app registers it only when enabled).
    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
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
    ).toBeVisible({ timeout: 60_000 });

    // The hook (integration_mattermost_provision.yml) registers an OAuth app on the
    // partner Mattermost and writes oauth_instance_url (= web-app-mattermost url.base)
    // + client_id + client_secret. When integration_mattermost is enabled the admin OAuth
    // instance URL MUST be configured and MUST point at the partner host, not Nextcloud.
    // An absent/empty/self-pointing instance URL means the coupling failed to provision —
    // the test FAILS here, it does not skip.
    await page.goto(
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});
    await page.waitForLoadState("networkidle").catch(() => {});

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const instanceFields = page.locator(
      'input[id*="mattermost-oauth-instance"], input[id*="mattermost"][id*="instance"], ' +
        'input[id*="mattermost"][type="url"]'
    );
    const instanceFieldCount = await instanceFields.count();
    let instanceHost = null;
    for (let i = 0; i < instanceFieldCount; i += 1) {
      const value = ((await instanceFields.nth(i).inputValue().catch(() => "")) || "").trim();
      if (/^https?:\/\//i.test(value)) {
        instanceHost = new URL(value).host;
        break;
      }
    }
    expect(
      instanceHost,
      "the Mattermost oauth_instance_url must be configured on the admin panel — its absence means the integration hook never provisioned the partner OAuth app"
    ).toBeTruthy();
    expect(
      instanceHost,
      "the configured Mattermost instance URL must be the partner host, not the Nextcloud host"
    ).not.toBe(nextcloudHost);

    const clientIdField = page
      .locator('input[id*="mattermost"][id*="client-id"], input[id*="mattermost-client-id"]')
      .first();
    const clientIdConfigured = page
      .getByText(/oauth client id|client secret|reset oauth|replace oauth/i)
      .first();
    await expect(
      clientIdField.or(clientIdConfigured),
      "the admin panel must expose the provisioned Mattermost OAuth client (proves the OAuth app was registered on the partner)"
    ).toBeVisible({ timeout: 60_000 });

    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});
    await page.waitForLoadState("networkidle").catch(() => {});

    // 3) The connect button performs the OAuth authorize redirect to the partner
    // Mattermost. This only works when the hook provisioned the OAuth client and
    // persisted client_id/oauth_instance_url. A token/login-only fallback would
    // NOT navigate off-Nextcloud to an /oauth/authorize endpoint.
    const popupPromise = page.waitForEvent("popup", { timeout: 15_000 }).catch(() => null);
    await Promise.all([
      page.waitForEvent("framenavigated", { timeout: 60_000 }).catch(() => {}),
      connect.click(),
    ]);

    const popup = await popupPromise;
    const currentUrl = () => (popup ? popup.url() : page.url());

    await expect
      .poll(currentUrl, { timeout: 60_000 })
      .toMatch(/\/oauth\/authorize\?/i);

    const authorizeUrl = new URL(currentUrl());

    expect(
      authorizeUrl.host,
      "Mattermost OAuth authorize must be served by the partner instance, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorizeUrl.host,
      "the OAuth authorize must land on the same partner host configured as oauth_instance_url"
    ).toBe(instanceHost);
    expect(
      authorizeUrl.searchParams.get("client_id"),
      "OAuth authorize must carry the provisioned Mattermost client_id"
    ).toBeTruthy();
    expect(authorizeUrl.searchParams.get("response_type")).toBe("code");

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
