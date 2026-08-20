const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

// Partner host comes from the env file — never hardcode the stack domain.
const mastodonPartnerHost = decodeDotenvQuotedValue(process.env.MASTODON_PARTNER_HOST || "");

// Functional cross-role coupling check for nextcloud/integration_mastodon.
//
// This is a bridge addon: integration_mastodon links Nextcloud to a deployed
// Mastodon partner instance. tasks/addons/integration_mastodon.yml +
// meta/addons/integration_mastodon.yml provision the app key oauth_instance_url
// (Settings/Admin.php) to the partner microblog host — the admin-level default the
// per-user OAuth connect flow falls back to. The real coupling is therefore twofold:
//   1. the admin "Mastodon integration" panel renders the provisioned partner
//      instance URL (a host distinct from Nextcloud), and
//   2. the per-user "Connect to Mastodon" handoff actually drives to the PARTNER's
//      /oauth/authorize endpoint carrying the provisioned client_id &
//      response_type=code (i.e. the bridge reaches the partner, not Nextcloud).
// When the addon is enabled, both MUST hold; a missing panel, missing connect
// control, or a redirect that never leaves Nextcloud means the coupling failed to
// provision and the test FAILS (it does not skip).
test("integration integration_mastodon: connects Nextcloud to the partner Mastodon via provisioned OAuth", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_mastodon");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    // Coupling signal 1: the admin Mastodon settings panel must render the
    // configured default instance address (oauth_instance_url) provisioned by the
    // addon hook. The field is an NcTextField bound to oauth_instance_url inside the
    // app's admin section (#mastodon_prefs / #mastodon-content) under the
    // "connected-accounts" admin settings page.
    await page.goto(
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const mastodonPanel = page
      .locator("#mastodon_prefs, #mastodon-content")
      .first();
    await expect(
      mastodonPanel,
      "the Mastodon integration admin panel must render when integration_mastodon is enabled — its absence means the app failed to install/configure and the coupling never landed"
    ).toBeVisible({ timeout: 60_000 });

    // The instance-address NcTextField has no stable id; locate the text input
    // inside the Mastodon panel whose value is an absolute URL. NcTextField may
    // wrap the native <input>, so search the panel for a URL-shaped value.
    const urlInputs = mastodonPanel.locator("input[type='text'], input[type='url'], input:not([type])");
    await expect(
      urlInputs.first(),
      "the Mastodon admin panel must expose the 'Default Mastodon instance address' field"
    ).toBeVisible({ timeout: 30_000 });

    const inputCount = await urlInputs.count();
    let configuredInstanceUrl = null;
    for (let i = 0; i < inputCount; i += 1) {
      const value = (await urlInputs.nth(i).inputValue().catch(() => "")) || "";
      if (/^https?:\/\//i.test(value.trim())) {
        configuredInstanceUrl = value.trim();
        break;
      }
    }

    expect(
      configuredInstanceUrl,
      "the Mastodon admin instance-address field must be populated with the partner URL (addon hook sets oauth_instance_url)"
    ).toBeTruthy();

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const instanceHost = new URL(configuredInstanceUrl).host;
    expect(
      instanceHost,
      "the configured Mastodon instance must be the partner instance, not Nextcloud itself"
    ).not.toBe(nextcloudHost);
    expect(
      mastodonPartnerHost,
      "MASTODON_PARTNER_HOST must be set in the Playwright env file"
    ).toBeTruthy();
    expect(
      instanceHost,
      "the Mastodon oauth_instance_url must point at the deployed microblog partner host"
    ).toBe(mastodonPartnerHost);

    // Coupling signal 2: the per-user "Connect to Mastodon" handoff must drive to
    // the PARTNER instance's /oauth/authorize endpoint, carrying the provisioned
    // OAuth client_id & response_type=code. This proves the bridge actually reaches
    // the partner (not Nextcloud) — the real federation/login round-trip.
    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const connect = page
      .getByRole("button", { name: /connect to mastodon/i })
      .or(page.getByRole("link", { name: /connect to mastodon/i }))
      .first();
    await expect(
      connect,
      "the 'Connect to Mastodon' control must render once oauth_instance_url is provisioned — its absence means the per-user OAuth bridge never wired up"
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
      .toMatch(/\/oauth\/authorize\?/i);

    const authorizeUrl = new URL(currentUrl());
    expect(
      authorizeUrl.host,
      "Mastodon OAuth authorize must be served by the partner instance, not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorizeUrl.host,
      "Mastodon OAuth authorize host must match the configured partner instance"
    ).toBe(instanceHost);
    expect(
      authorizeUrl.searchParams.get("client_id"),
      "the authorize redirect must carry the provisioned Mastodon OAuth client_id"
    ).toBeTruthy();
    expect(authorizeUrl.searchParams.get("response_type")).toBe("code");

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
