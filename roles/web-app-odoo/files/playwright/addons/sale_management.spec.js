const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon sale_management: Sales module is installed and serves its quotations action", async ({ browser }) => {
  skipUnlessAddonEnabled("sale_management");
  test.setTimeout(180_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    await shared.openModule(page, "odoo/sales");

    const breadcrumb = page
      .locator(".o_breadcrumb, .o_control_panel .o_breadcrumb, .breadcrumb-item.active, .o_last_breadcrumb_item")
      .filter({ hasText: /sales|quotation|order/i })
      .first();
    const appTitle = page
      .locator(".o_menu_brand, .o_navbar .o_menu_sections, .o_control_panel")
      .getByText(/sales|quotations|orders/i)
      .first();
    const salesIdentity = breadcrumb.or(appTitle).first();
    await expect(
      salesIdentity,
      "the Sales app identity (breadcrumb/title naming Sales/Quotations/Orders) must render — when sale_management is enabled but the module failed to install, /odoo/sales falls back to the generic home shell and this is absent, so the test MUST fail here, not pass on the bare web client"
    ).toBeVisible({ timeout: 90_000 });

    const quotationsAction = page
      .locator(".o_list_view, .o_kanban_view, .o_list_renderer, .o_kanban_renderer")
      .first();
    await expect(
      quotationsAction,
      "the sale.order quotations action (list/kanban) must render — its presence proves the Sales module's server action is actually wired, not just that some Odoo page loaded"
    ).toBeVisible({ timeout: 90_000 });

    const createQuotation = page
      .locator(".o_control_panel button.o_list_button_add, .o_control_panel .o-kanban-button-new")
      .or(page.getByRole("button", { name: /^new$/i }))
      .first();
    await expect(
      createQuotation,
      "the Sales control panel must expose the 'New' create button for sale.order — confirms the module's create action is live, distinguishing a real Sales surface from the generic Odoo shell"
    ).toBeVisible({ timeout: 90_000 });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
