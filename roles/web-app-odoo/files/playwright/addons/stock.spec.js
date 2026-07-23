const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon stock: Inventory module is installed and serves its warehouse operations action", async ({ browser }) => {
  skipUnlessAddonEnabled("stock");
  test.setTimeout(resolveTimeout(180_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    await shared.openModule(page, "odoo/inventory");

    const breadcrumb = page
      .locator(".o_breadcrumb, .o_control_panel .o_breadcrumb, .breadcrumb-item.active, .o_last_breadcrumb_item")
      .filter({ hasText: /inventory|operation|transfer|receipt|delivery|warehouse/i });
    const appTitle = page
      .locator(".o_menu_brand, .o_navbar .o_menu_sections, .o_control_panel")
      .getByText(/inventory|operations|transfers|warehouse/i);
    const inventoryIdentity = breadcrumb.or(appTitle).first();
    await expect(
      inventoryIdentity,
      "the Inventory app identity (breadcrumb/title naming Inventory/Operations/Transfers/Warehouse) must render — when stock is enabled but the module failed to install, /odoo/inventory falls back to the generic home shell and this is absent, so the test MUST fail here, not pass on the bare web client"
    ).toBeVisible({ timeout: resolveTimeout(90_000) });

    const actionError = page
      .locator(".o_error_dialog, .modal-content")
      .getByText(/invalid action|action.*not found|no action|odoo (server|client) error/i)
      .first();
    await expect(
      actionError,
      "navigating to the Inventory action must not raise an Odoo 'invalid action' error — if the stock module is not installed the inventory.action menu does not exist and Odoo errors instead of rendering the app"
    ).toHaveCount(0, { timeout: resolveTimeout(30_000) });

    const operationsAction = page
      .locator(".o_kanban_view, .o_kanban_renderer, .o_list_view, .o_list_renderer")
      .first();
    await expect(
      operationsAction,
      "the stock.picking.type operations dashboard (kanban/list of Receipts/Deliveries/Internal Transfers) must render — its presence proves the stock module's server action is actually wired, not just that some Odoo page loaded"
    ).toBeVisible({ timeout: resolveTimeout(90_000) });

    const stockSurface = page
      .locator(".o_control_panel")
      .getByText(/receipt|deliver|transfer|operation|to process/i)
      .or(page.locator(".o_kanban_record, .o_data_row").filter({ hasText: /receipt|deliver|transfer|internal/i }))
      .first();
    await expect(
      stockSurface,
      "the Inventory dashboard must expose stock-specific operation types (Receipts/Deliveries/Internal Transfers) — confirms the stock model's action is live, distinguishing a real Inventory surface from the generic Odoo shell"
    ).toBeVisible({ timeout: resolveTimeout(90_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
