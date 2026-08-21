const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon website: website module UI renders", async ({ browser }) => {
  skipUnlessAddonEnabled("website");

  const { context, page } = await shared.authenticatedContext(browser);

  try {
    await shared.openModule(page, "odoo/website");

    const surface = page.locator(
      ".o_web_client, .o_action_manager, .o_main_navbar, .o_content, .o_website_preview, iframe.o_iframe"
    );
    await expect(surface.first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
