const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("integration integration_github: per-user OAuth connect reaches github.com/login/oauth/authorize with the provisioned client_id", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_github");
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

    const connect = page.getByRole("button", { name: /connect to github with oauth/i });
    await expect(
      connect.first(),
      "the 'Connect to GitHub with OAuth' control must render once the admin OAuth client_id is provisioned — its absence means the github.client_id/client_secret api wiring failed to land"
    ).toBeVisible({ timeout: 60_000 });

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;

    await Promise.all([
      page
        .waitForURL((u) => /^https?:\/\/github\.com\/login\/oauth\/authorize(?:[/?#]|$)/i.test(u), { timeout: 60_000 })
        .catch(() => {}),
      connect.first().click(),
    ]);

    await expect
      .poll(() => page.url(), { timeout: 60_000 })
      .toMatch(/^https?:\/\/github\.com\/login\/oauth\/authorize(?:[/?#]|$)/i);

    const authorize = new URL(page.url());
    expect(
      authorize.host,
      "the OAuth connect must hand off to the partner GitHub (github.com), not stay on the Nextcloud host"
    ).toBe("github.com");
    expect(authorize.host, "the authorize endpoint must not be Nextcloud itself").not.toBe(nextcloudHost);
    expect(
      authorize.pathname,
      "the connect must reach GitHub's authorization-code endpoint"
    ).toBe("/login/oauth/authorize");
    expect(
      (authorize.searchParams.get("client_id") || "").length,
      "the authorize redirect must carry the provisioned GitHub OAuth client_id (proves the github.client_id api wiring is live)"
    ).toBeGreaterThan(0);
    expect(
      authorize.searchParams.get("redirect_uri") || "",
      "the authorize redirect_uri must point back at this Nextcloud instance to complete the code grant"
    ).toContain(nextcloudHost);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
