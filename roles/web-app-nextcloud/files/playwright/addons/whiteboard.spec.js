const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("whiteboard addon: admin whiteboard settings render and are wired to the collab backend", async ({ browser }) => {
  skipUnlessAddonEnabled("whiteboard");
  test.setTimeout(resolveTimeout(120_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToStandaloneNextcloud(page);

    await page.goto(
      new URL("settings/admin/whiteboard", shared.env.nextcloudBaseUrl).toString(),
      { waitUntil: "domcontentloaded", timeout: resolveTimeout(60_000) }
    );
    await shared.dismissBlockingNextcloudModals(page, page);

    await expect(
      page.locator("#app-content, #app-content-vue, #content").first(),
      "the Whiteboard admin settings shell (settings/admin/whiteboard) must render, proving the whiteboard app is installed AND enabled (a disabled/broken app yields no section)"
    ).toBeVisible({ timeout: resolveTimeout(60_000) });

    const urlState = page.locator("#initial-state-whiteboard-url");
    await expect(
      urlState,
      "the whiteboard admin settings must inject its server-URL initial-state (#initial-state-whiteboard-url), proving the app's admin section rendered with its config"
    ).toHaveCount(1);

    const rawUrl =
      (await urlState.inputValue().catch(() => "")) ||
      (await urlState.getAttribute("value").catch(() => "")) ||
      "";
    let url = "";
    try {
      url = JSON.parse(Buffer.from(rawUrl, "base64").toString("utf8"));
    } catch {
      url = "";
    }
    expect(
      typeof url === "string" && /^https?:\/\//.test(url),
      "the whiteboard collab-backend URL must be configured (NEXTCLOUD_WHITEBOARD_URL via plugin_configuration), not blank"
    ).toBeTruthy();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
