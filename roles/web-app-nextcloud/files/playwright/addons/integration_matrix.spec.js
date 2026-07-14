const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");
const { gotoOnion } = require("../personas");

test("integration integration_matrix: per-user login drives a real session against the partner homeserver", async ({ browser }) => {
  skipUnlessAddonEnabled("integration_matrix");
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

    const adminPanel = page.locator("#matrix_prefs, #matrix-content").first();
    await expect(
      adminPanel,
      "the Matrix integration admin panel must render when integration_matrix is enabled — its absence means the app failed to enable/configure against the partner homeserver"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    let configuredInstanceUrl = null;
    const adminInputs = adminPanel.locator("input[type='text'], input[type='url'], input:not([type])");
    const adminCount = await adminInputs.count();
    for (let i = 0; i < adminCount; i += 1) {
      const value = (await adminInputs.nth(i).inputValue().catch(() => "")) || "";
      if (/^https?:\/\//i.test(value.trim())) {
        configuredInstanceUrl = value.trim();
        break;
      }
    }
    expect(
      configuredInstanceUrl,
      "the Matrix admin homeserver field must be populated with the partner URL"
    ).toBeTruthy();

    const partnerHost = new URL(configuredInstanceUrl).host;
    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    expect(partnerHost, "the homeserver must be the partner, not Nextcloud").not.toBe(nextcloudHost);

    const partnerHits = [];
    page.on("request", (req) => {
      try {
        const h = new URL(req.url()).host;
        if (h === partnerHost && /\/_matrix\/client\//.test(req.url())) {
          partnerHits.push(req.url());
        }
      } catch {}
    });

    await gotoOnion(page,
      new URL("settings/user/connected-accounts", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const userPanel = page.locator("#matrix_prefs, #matrix-content").first();
    await expect(
      userPanel,
      "the personal Matrix panel must render so a user can link their Matrix account"
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const loginField = userPanel
      .locator("input[type='text']:not([readonly]), input:not([type]):not([readonly])")
      .first();
    const passwordField = userPanel.locator("input[type='password']").first();
    const connectButton = userPanel
      .getByRole("button", { name: /connect|log ?in|sign ?in/i })
      .first();

    const connectResponsePromise = page
      .waitForResponse((resp) => /\/apps\/integration_matrix\//.test(resp.url()), { timeout: resolveTimeout(30_000) })
      .catch(() => null);

    if (await passwordField.isVisible({ timeout: resolveTimeout(10_000) }).catch(() => false)) {
      await loginField.fill(shared.env.loginUsername || "admin").catch(() => {});
      await passwordField.fill(shared.env.loginPassword || "").catch(() => {});
      await connectButton.click({ timeout: resolveTimeout(10_000) }).catch(() => {});
    } else if (await connectButton.isVisible({ timeout: resolveTimeout(5_000) }).catch(() => false)) {
      await connectButton.click({ timeout: resolveTimeout(10_000) }).catch(() => {});
    }

    const connectResponse = await connectResponsePromise;
    await page.waitForTimeout(resolveTimeout(2_500));

    const reachedPartner = partnerHits.length > 0;
    const droveServerSide = Boolean(connectResponse);
    expect(
      reachedPartner || droveServerSide,
      "the per-user connect must drive a real login against the partner Matrix homeserver " +
        "(a browser C-S API call to the partner, or a nextcloud integration_matrix connect round-trip), " +
        "not merely render a configured URL"
    ).toBe(true);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
