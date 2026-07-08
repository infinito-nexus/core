const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("richdocuments addon: Collabora connector wired to the partner WOPI server", async ({ browser }) => {
  skipUnlessAddonEnabled("richdocuments");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/admin/richdocuments", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    const adminSection = page
      .locator("#richdocuments, [data-cy='collabora-server-settings']")
      .or(page.getByText(/collabora online/i).first());
    await expect(
      adminSection.first(),
      "the Collabora Online (richdocuments) admin settings section must render, proving the app is enabled"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const wopiField = page
      .locator("#wopi_url, input[name='wopi_url'], input[id*='wopi' i]")
      .first();
    await expect(
      wopiField,
      "the Collabora server URL (WOPI) field must render in the admin panel"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });
    const wopiValue = ((await wopiField.inputValue().catch(() => "")) || "").trim();
    expect(
      /^https?:\/\/.+/.test(wopiValue),
      "the WOPI server URL must be a real partner URL (config:app:set wopi_url); empty means the partner endpoint was never wired"
    ).toBeTruthy();
    expect(
      new URL(wopiValue).host,
      "the WOPI server URL must point at the partner Collabora host, not Nextcloud itself"
    ).not.toBe(new URL(shared.env.nextcloudBaseUrl).host);

    const connectionError = page.getByText(
      /could not establish connection to the collabora online server|failed to connect|not a valid (collabora|wopi)/i
    );
    await expect(
      connectionError,
      "the Collabora connection-failure banner must be absent: richdocuments must reach the partner WOPI server (config:app:set wopi_url + occ richdocuments:activate-config discovery)"
    ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
