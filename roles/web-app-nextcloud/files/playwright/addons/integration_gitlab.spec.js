const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("integration integration_gitlab: per-user OAuth connect reaches the partner GitLab authorize endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_gitlab");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await gotoOnion(page,
      new URL("settings/admin/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const instanceInput = page.locator("#gitlab-oauth-instance");
    await expect(
      instanceInput.first(),
      "the GitLab admin OAuth instance field must render when integration_gitlab is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    const instanceUrl = ((await instanceInput.first().inputValue()) || "").trim();
    expect(instanceUrl.length, "oauth_instance_url must be configured").toBeGreaterThan(0);

    const partnerHost = new URL(instanceUrl).host;
    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    expect(partnerHost, "must point at the partner GitLab, not the gitlab.com default").not.toBe("gitlab.com");
    expect(partnerHost, "must not point back at Nextcloud itself").not.toBe(nextcloudHost);

    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const connect = page
      .locator('a[href*="/oauth/authorize"], a:has-text("Connect to GitLab"), button:has-text("Connect to GitLab")')
      .first();
    await expect(
      connect,
      "the personal 'Connect to GitLab' control must render once the partner OAuth client is provisioned"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const requestPromise = context
      .waitForEvent("request", {
        predicate: (req) => new URL(req.url()).host === partnerHost && req.url().includes("/oauth/authorize"),
        timeout: resolveTimeout(30_000),
      })
      .catch(() => null);
    await connect.click({ timeout: resolveTimeout(10_000) });
    const request = await requestPromise;
    const response = request ? await request.response().catch(() => null) : null;

    const authorize = new URL(request ? request.url() : page.url(), instanceUrl);
    expect(
      authorize.host,
      `the per-user connect must hand off to the partner GitLab (got ${authorize.href})`
    ).toBe(partnerHost);
    expect(
      authorize.pathname,
      `the per-user connect must initiate OAuth on the partner /oauth/authorize endpoint (got ${authorize.href})`
    ).toContain("/oauth/authorize");
    expect(
      (authorize.searchParams.get("client_id") || "").length,
      "the authorize request must carry the provisioned OAuth client_id (proves the partner-registered app)"
    ).toBeGreaterThan(0);
    expect(
      authorize.searchParams.get("response_type"),
      "the coupling must use the authorization-code grant"
    ).toBe("code");
    expect(
      new URL(authorize.searchParams.get("redirect_uri") || "", instanceUrl).host,
      "the authorize request must hand the code back to this Nextcloud, not a third party"
    ).toBe(nextcloudHost);
    expect(
      response ? response.status() : 599,
      `the partner GitLab must answer the authorize request (got ${response ? response.status() : "no response"})`
    ).toBeLessThan(400);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
