const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("bbb addon: cloud_bbb app route renders its own UI and is coupled to the partner server", async ({ browser }) => {
  skipUnlessAddonEnabled("bbb");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    const appUrl = new URL("apps/bbb/", shared.env.nextcloudBaseUrl).toString();
    await page.goto(appUrl, { waitUntil: "commit", timeout: resolveTimeout(60_000) });
    await shared.dismissBlockingNextcloudModals(page, page);

    const appContainer = page.locator(
      "#app-content, #app-content-vue, #content, #content-vue"
    );
    await expect(
      appContainer.first(),
      "the cloud_bbb app shell must render at /apps/bbb/ (the app is installed and enabled)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const bbbAppSurface = page.locator(
      "#bbb, .app-bbb, [id^='bbb'], a[href*='/apps/bbb']"
    );
    await expect(
      bbbAppSurface.first(),
      "the cloud_bbb app's own UI surface (its room-management view / active app menu entry) must render, so a disabled or broken bbb app fails"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    await page.goto(
      new URL("settings/admin/additional", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const bbbSection = page.locator("#bbb-settings");
    await expect(
      bbbSection.first(),
      "the cloud_bbb admin settings section (#bbb-settings) must render on the additional admin page, proving the bbb app is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const apiUrlField = bbbSection.locator("#bbb-api input[name='api.url'], input[name='api.url']");
    await expect(
      apiUrlField.first(),
      "the BigBlueButton (bbb) admin settings section must expose the api.url field"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const configuredUrl = ((await apiUrlField.first().inputValue().catch(() => "")) || "").trim();
    expect(
      configuredUrl.length,
      "the bbb api.url field must be populated from config:app:set so the BigBlueButton partner endpoint is wired"
    ).toBeGreaterThan(0);

    expect(
      configuredUrl,
      "the bbb api.url must be a valid https URL pointing at the BigBlueButton API mount (the partner base URL + '/bigbluebutton/' API suffix)"
    ).toMatch(/^https:\/\/.+\/bigbluebutton\/?$/);

    const apiSecretField = bbbSection.locator("#bbb-api input[name='api.secret'], input[name='api.secret']");
    await expect(
      apiSecretField.first(),
      "the bbb settings must expose the api.secret field; together with api.url it forms the partner coupling written via config:app:set"
    ).toBeAttached({ timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
