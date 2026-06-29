const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

// Functional cross-role / bridge check for nextcloud/integration_jira.
//
// The addon is wired with a real Atlassian OAuth client (client_id/client_secret
// rendered from the `api` lookup in meta/addons/integration_jira.yml). The partner
// is Atlassian Jira Cloud — an external SaaS at auth.atlassian.com, with no
// self-hosted role — so when no live Atlassian credentials are provisioned the
// computed enabled flag is false and skipUnlessAddonEnabled skips this test.
//
// When it IS enabled the real coupling is the per-user OAuth "Connect to Jira
// Cloud" handing the browser off to the PARTNER's authorize endpoint
// (auth.atlassian.com/authorize) carrying the provisioned client_id and the
// authorization-code grant (response_type=code). Reaching the partner host —
// distinct from Nextcloud — with the provisioned client proves the integration
// URL + client are live. Full consent needs live Atlassian credentials (a
// separate Tier-2 concern); we stop at the partner authorize redirect.
test("integration integration_jira: per-user OAuth connect reaches the Atlassian Jira Cloud authorize endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_jira");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);
    await page.goto(
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    // The "Connect to Jira Cloud" NcButton only renders once the admin client_id
    // is configured; it navigates the top frame via window.location.replace() to
    // auth.atlassian.com/authorize. Its absence means the OAuth client failed to
    // provision — that MUST fail the test, not skip it.
    const connect = page
      .getByRole("button", { name: /connect to jira cloud/i })
      .or(page.getByRole("link", { name: /connect to jira cloud/i }))
      .first();
    await expect(
      connect,
      "the per-user 'Connect to Jira Cloud' control must render once the Atlassian OAuth client is provisioned — its absence means the coupling failed to land"
    ).toBeVisible({ timeout: 60_000 });

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const popupPromise = context.waitForEvent("page", { timeout: 15_000 }).catch(() => null);
    await Promise.all([
      page
        .waitForURL((u) => /^https?:\/\/auth\.atlassian\.com(?:[:/?#]|$)/i.test(String(u)), { timeout: 60_000 })
        .catch(() => {}),
      connect.click(),
    ]);

    const popup = await popupPromise;
    const target = popup || page;
    await target.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
    await expect
      .poll(() => target.url(), { timeout: 60_000 })
      .toMatch(/^https?:\/\/auth\.atlassian\.com\/authorize(?:[?#/]|$)/i);

    const authorize = new URL(target.url());
    expect(
      authorize.host,
      "the Jira Cloud OAuth authorize must be served by Atlassian (auth.atlassian.com), the partner — not Nextcloud"
    ).toBe("auth.atlassian.com");
    expect(
      authorize.host,
      "the authorize host must not point back at Nextcloud itself"
    ).not.toBe(nextcloudHost);
    expect(
      authorize.pathname,
      "the per-user connect must initiate the OAuth 3LO flow on the partner /authorize endpoint"
    ).toContain("/authorize");
    expect(
      (authorize.searchParams.get("client_id") || "").length,
      "the authorize redirect must carry the provisioned Atlassian OAuth client_id (proves the partner-registered app)"
    ).toBeGreaterThan(0);
    expect(
      authorize.searchParams.get("response_type"),
      "the coupling must use the authorization-code grant"
    ).toBe("code");

    if (popup) await popup.close().catch(() => {});
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
