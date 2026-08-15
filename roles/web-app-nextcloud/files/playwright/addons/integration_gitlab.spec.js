const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("integration integration_gitlab: per-user OAuth connect reaches the partner GitLab authorize endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_gitlab");
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

    const instanceInput = page.locator("#gitlab-oauth-instance");
    await expect(
      instanceInput.first(),
      "the GitLab admin OAuth instance field must render when integration_gitlab is enabled"
    ).toBeVisible({ timeout: 60_000 });
    const instanceUrl = ((await instanceInput.first().inputValue()) || "").trim();
    expect(instanceUrl.length, "oauth_instance_url must be configured").toBeGreaterThan(0);

    const partnerHost = new URL(instanceUrl).host;
    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    expect(partnerHost, "must point at the partner GitLab, not the gitlab.com default").not.toBe("gitlab.com");
    expect(partnerHost, "must not point back at Nextcloud itself").not.toBe(nextcloudHost);

    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const connect = page
      .locator('a[href*="/oauth/authorize"], a:has-text("Connect to GitLab"), button:has-text("Connect to GitLab")')
      .first();
    await expect(
      connect,
      "the personal 'Connect to GitLab' control must render once the partner OAuth client is provisioned"
    ).toBeVisible({ timeout: 30_000 });

    let authorizeUrl = await connect.getAttribute("href").catch(() => null);
    if (!authorizeUrl || !/\/oauth\/authorize/i.test(authorizeUrl)) {
      // The control is a button doing window.location.replace(<partner>/oauth/authorize?...); GitLab
      // bounces the unauthenticated browser to /users/sign_in, so the settled URL is no longer the
      // authorize endpoint. Capture the authorize request itself, which carries the provisioned client_id.
      const requestPromise = page
        .waitForRequest((req) => /\/oauth\/authorize/i.test(req.url()), { timeout: 30_000 })
        .catch(() => null);
      await connect.click({ timeout: 10_000 }).catch(() => {});
      const request = await requestPromise;
      authorizeUrl = request ? request.url() : page.url();
    }

    const authorize = new URL(authorizeUrl, instanceUrl);
    const initiatedOnPartner =
      authorize.host === partnerHost && authorize.pathname.includes("/oauth/authorize");
    expect(
      initiatedOnPartner,
      `the per-user connect must initiate OAuth on the partner GitLab (got ${authorize.href})`
    ).toBe(true);

    const authorizeQuery = authorize.searchParams;
    expect(
      (authorizeQuery.get("client_id") || "").length,
      "the authorize request must carry the provisioned OAuth client_id (proves the partner-registered app)"
    ).toBeGreaterThan(0);
    expect(
      authorizeQuery.get("response_type"),
      "the coupling must use the authorization-code grant"
    ).toBe("code");
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
