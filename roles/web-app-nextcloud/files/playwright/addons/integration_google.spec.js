const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("integration integration_google: per-user OAuth connect reaches the Google authorize endpoint", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_google");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  const connectFor = (target) =>
    target.getByRole("button", { name: /sign in with google/i });

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/user/migration", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: 60_000 }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    let connect = connectFor(page);
    if ((await connect.count()) === 0) {
      await page.goto(
        new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
        { waitUntil: "domcontentloaded", timeout: 60_000 }
      );
      await shared.dismissBlockingNextcloudModals(page, page);
      connect = connectFor(page);
    }

    await expect(
      connect.first(),
      "the 'Sign in with Google' control must render once the integration_google OAuth client_id is provisioned — its absence means the meta/addons client_id/client_secret coupling failed to land"
    ).toBeVisible({ timeout: 60_000 });

    const popupPromise = context.waitForEvent("page", { timeout: 15_000 }).catch(() => null);
    await Promise.all([
      page
        .waitForURL((u) => /^accounts\.google\.com$/i.test(new URL(u).host), { timeout: 60_000 })
        .catch(() => {}),
      connect.first().click(),
    ]);
    const popup = await popupPromise;
    const target = popup || page;
    await target.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});

    const authorize = new URL(target.url());
    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;

    expect(
      authorize.host,
      `the per-user connect must hand the browser off to the Google authorize endpoint, not stay on Nextcloud (got ${authorize.href})`
    ).toBe("accounts.google.com");
    expect(
      authorize.host,
      "the Google OAuth authorize must be served by the partner (accounts.google.com), not Nextcloud"
    ).not.toBe(nextcloudHost);
    expect(
      authorize.pathname,
      "the connect must drive the Google OAuth2 authorize path"
    ).toMatch(/^\/o\/oauth2(\/v2)?\/auth/);
    expect(
      (authorize.searchParams.get("client_id") || "").length,
      "the authorize request must carry the provisioned Google OAuth client_id (proves the client_id from meta/addons is live)"
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
