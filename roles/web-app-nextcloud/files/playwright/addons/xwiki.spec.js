const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

// Partner host comes from the env file — never hardcode the stack domain.
const xwikiPartnerHost = decodeDotenvQuotedValue(process.env.XWIKI_PARTNER_HOST || "");

test.use({ ignoreHTTPSErrors: true });

test("xwiki addon: Nextcloud admin XWiki app renders and is coupled to the partner instance", async ({ browser }) => {
  skipUnlessAddonEnabled("xwiki");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const settingsUrl = new URL("settings/admin/xwiki", shared.env.nextcloudBaseUrl).toString();
    const response = await page.goto(settingsUrl, {
      waitUntil: "domcontentloaded",
      timeout: 60_000
    });
    expect(
      response === null || response.status() !== 404,
      "the xwiki app must register its settings/admin/xwiki section (app installed + enabled)"
    ).toBeTruthy();
    await shared.dismissBlockingNextcloudModals(page, page);

    const instanceList = page.locator("#xwiki-admin-instance-list").first();
    await expect(
      instanceList,
      "the xwiki app must render its own admin instances table (disabled/broken app never mounts it)"
    ).toBeVisible({ timeout: 60_000 });

    const noWikis = page.locator("#no-wikis-registered-p");
    await expect(
      noWikis,
      "XWiki must report at least one registered instance (instances appValue must be valid JSON coupling to the partner)"
    ).toHaveCount(0);

    const urlInputs = instanceList.locator("input[name='instance-url']");
    const inputCount = await urlInputs.count();
    expect(
      inputCount,
      "the XWiki admin table must render at least one instance-url input"
    ).toBeGreaterThan(0);

    let configuredUrl = null;
    for (let i = 0; i < inputCount; i += 1) {
      const value = (await urlInputs.nth(i).inputValue().catch(() => "")) || "";
      if (/^https?:\/\//i.test(value.trim())) {
        configuredUrl = value.trim();
        break;
      }
    }

    expect(
      configuredUrl,
      "the XWiki admin instances table must contain a populated instance-url (addon hook writes valid-JSON instances)"
    ).toBeTruthy();

    const nextcloudHost = new URL(shared.env.nextcloudBaseUrl).host;
    const instanceHost = new URL(configuredUrl).host;
    expect(
      instanceHost,
      "the configured XWiki instance must be the partner instance, not Nextcloud itself"
    ).not.toBe(nextcloudHost);
    expect(
      xwikiPartnerHost,
      "XWIKI_PARTNER_HOST must be set in the Playwright env file"
    ).toBeTruthy();
    expect(
      instanceHost,
      "the XWiki instances appValue must point at the deployed XWiki partner host"
    ).toBe(xwikiPartnerHost);
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
