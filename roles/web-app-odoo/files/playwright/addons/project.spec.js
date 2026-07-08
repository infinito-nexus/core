const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon project: project module UI renders", async ({ browser }) => {
  skipUnlessAddonEnabled("project");

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    await shared.openModule(page, "odoo/project");

    const surface = page.locator(
      ".o_web_client, .o_action_manager, .o_main_navbar, .o_content, .o_kanban_view"
    );
    await expect(surface.first()).toBeVisible({ timeout: resolveTimeout(60_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
