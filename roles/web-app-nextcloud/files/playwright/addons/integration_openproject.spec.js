const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("integration integration_openproject: two-way OAuth coupling provisioned and connectable to partner OpenProject", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_openproject");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/admin/openproject", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const adminSection = page
      .locator("#openproject_prefs, #openproject-server-host, #openproject-prefs")
      .or(page.getByText(/openproject/i))
      .first();
    await expect(
      adminSection,
      "the OpenProject integration admin settings section must render when the addon is enabled"
    ).toBeVisible({ timeout: 60_000 });

    const oauthConfigured = page
      .locator('input[id*="openproject-oauth-client-id"], input[id*="client-id"], input[id*="client-secret"]')
      .or(page.getByText(/reset oauth|replace oauth|nextcloud oauth (client|values)/i))
      .or(page.getByText(/oauth client id|client secret/i))
      .first();
    await expect(
      oauthConfigured,
      "the admin panel must show the provisioned OAuth client (proves the two-way OAuth pair is registered on BOTH sides). When integration_openproject is enabled but this is absent, the coupling failed to provision — the test MUST fail here, not skip."
    ).toBeVisible({ timeout: 60_000 });

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const adminConfig = page.locator(
      "#initial-state-integration_openproject-admin-settings-config"
    );
    let instanceHost = null;
    let clientId = "";
    let clientSecret = "";
    let authMethod = "";
    if (await adminConfig.count()) {
      const raw =
        (await adminConfig.inputValue().catch(() => "")) ||
        (await adminConfig.getAttribute("value").catch(() => "")) ||
        "";
      let decoded;
      try {
        decoded = Buffer.from(raw, "base64").toString("utf8");
      } catch {
        decoded = raw;
      }
      try {
        const cfg = JSON.parse(decoded);
        const url = cfg.openproject_instance_url || "";
        if (/^https?:\/\//.test(url)) instanceHost = new URL(url).host;
        clientId = cfg.openproject_client_id || "";
        clientSecret = cfg.openproject_client_secret || "";
        authMethod = cfg.authorization_method || "";
      } catch {
        instanceHost = null;
      }
    }
    expect(instanceHost, "the OpenProject instance URL must be configured on the admin panel (integration_openproject openproject_instance_url)").toBeTruthy();
    expect(
      instanceHost,
      "the configured OpenProject instance URL must be the partner host, not the Nextcloud host"
    ).not.toBe(nextcloudHost);

    expect(
      clientId.length,
      "the OpenProject OAuth application client_id must be provisioned on the partner and linked into integration_openproject (the NC->OP half of the two-way OAuth coupling)"
    ).toBeGreaterThan(0);
    expect(
      clientSecret.length,
      "the OpenProject OAuth application client_secret must be linked into integration_openproject (proves the partner registered the OAuth app and returned its secret)"
    ).toBeGreaterThan(0);
    expect(
      authMethod,
      "integration_openproject must be wired for the OAuth2 authorization method once the bidirectional coupling is provisioned"
    ).toBe("oauth2");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
