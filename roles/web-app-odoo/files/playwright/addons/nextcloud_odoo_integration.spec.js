const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon nextcloud_odoo_integration: the paid Nextcloud sync module registers its settings surface", async ({ browser }) => {
  skipUnlessAddonEnabled("nextcloud_odoo_integration");

  const { context, page } = await shared.authenticatedContext(browser);

  try {
    await shared.openModule(page, "odoo/action-base_setup.action_general_configuration");

    const errorPage = page.locator(".o_error_dialog, .o_error_detail").or(
      page.getByText(/sorry,?\s*(this page|the page).*(not found|does not exist)|page not found|404 not found/i)
    );
    await expect(
      errorPage,
      "opening the general settings action must not render an Odoo error/not-found page"
    ).toHaveCount(0);

    await expect(
      page.locator("body"),
      "the general settings page must expose the Nextcloud section the module adds; its absence means a licensed copy of nextcloud_odoo_integration was never staged into files/addons/, so no calendar or contact sync reaches the partner Nextcloud"
    ).toContainText(/nextcloud/i, { timeout: resolveTimeout(120_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
