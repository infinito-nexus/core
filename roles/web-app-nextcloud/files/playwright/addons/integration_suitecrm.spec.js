const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("integration integration_suitecrm: per-user OAuth password grant reaches the partner SuiteCRM token endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_suitecrm");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page).catch(() => {});

    const suitecrmPanel = page.locator("#suitecrm_prefs").first();
    await expect(
      suitecrmPanel,
      "the SuiteCRM personal settings panel must render when integration_suitecrm is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const oauthContent = suitecrmPanel.locator("#suitecrm-content");
    await expect(
      oauthContent,
      "the SuiteCRM OAuth settings (#suitecrm-content) must render — its absence means the OAuth client was not provisioned"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const instanceField = suitecrmPanel.locator("#suitecrm-url");
    const instanceUrl = ((await instanceField.inputValue().catch(() => "")) || "").trim();
    expect(
      /^https?:\/\//i.test(instanceUrl),
      "oauth_instance_url must be a real partner URL pinned into the connect panel"
    ).toBeTruthy();

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const partnerHost = new URL(instanceUrl).host;
    expect(
      partnerHost,
      "the configured SuiteCRM instance must be the partner host, not Nextcloud itself"
    ).not.toBe(nextcloudHost);

    const loginField = suitecrmPanel.locator("#suitecrm-login");
    const passwordField = suitecrmPanel.locator("#suitecrm-password");
    const connectButton = suitecrmPanel.locator("#suitecrm-oauth");

    await expect(
      connectButton,
      "the 'Connect to SuiteCRM' control must render once the partner OAuth client is provisioned"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    await loginField.fill(shared.env.loginUsername);
    await passwordField.fill(shared.env.loginPassword);

    const connectResponsePromise = page.waitForResponse(
      (response) =>
        /\/apps\/integration_suitecrm\/oauth-connect$/.test(new URL(response.url()).pathname) &&
        response.request().method() === "POST",
      { timeout: resolveTimeout(60_000) }
    );
    await connectButton.click({ timeout: resolveTimeout(30_000) });
    const connectResponse = await connectResponsePromise;

    const connectStatus = connectResponse.status();
    const connectBody = await connectResponse.json().catch(() => ({}));

    expect(
      [200, 401].includes(connectStatus),
      `the oauth-connect token exchange must resolve to a partner auth verdict (200 connected or 401 invalid-credentials), got ${connectStatus} ${JSON.stringify(connectBody)}`
    ).toBeTruthy();

    if (connectStatus === 200) {
      expect(
        connectBody.user_name,
        "a successful password-grant connect must return the authenticated SuiteCRM user_name"
      ).toBeTruthy();
      await expect(
        suitecrmPanel.getByText(/connected as/i),
        "the panel must flip to a connected state after a successful partner token exchange"
      ).toBeVisible({ timeout: resolveTimeout(30_000) });
      await expect(suitecrmPanel.locator("#suitecrm-rm-cred")).toBeVisible({ timeout: resolveTimeout(30_000) });
    } else {
      expect(
        connectBody.error,
        "a refused password grant must surface the partner's invalid-credentials verdict, proving the token request reached the partner client rather than failing on missing config"
      ).toMatch(/invalid login\/password/i);
    }
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
