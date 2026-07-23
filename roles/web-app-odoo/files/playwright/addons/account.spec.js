const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon account: Accounting/Invoicing module is installed and serves its customer-invoices action", async ({ browser }) => {
  skipUnlessAddonEnabled("account");
  test.setTimeout(resolveTimeout(180_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    // Odoo 19 resolves the account module's Customer Invoices action at the
    // /odoo/invoicing deep-link (title "Invoices"); the Accounting dashboard at
    // /odoo/accounting only shows journal cards. When the account module is not
    // installed both routes degrade to the default home app (Discuss), which has
    // none of the invoice vocabulary asserted below.
    await shared.openModule(page, "odoo/invoicing");

    const errorPage = page.locator(".o_error_dialog, .o_error_detail").or(
      page.getByText(/invalid action|action.*not found|sorry,?\s*(this page|the page).*(not found|does not exist)|page not found|404 not found/i)
    );
    await expect(
      errorPage,
      "opening the Invoicing action must not render an Odoo error/not-found/invalid-action page; when account is enabled but the module is not installed the action xmlid does not exist and Odoo errors instead of rendering the app"
    ).toHaveCount(0);

    const invoicesAction = page
      .locator(".o_list_view, .o_list_renderer, .o_kanban_view, .o_kanban_renderer")
      .first();
    await expect(
      invoicesAction,
      "the account.move customer-invoices action (list/kanban) must render — its presence proves the account module's server action is actually wired, not just that some Odoo page loaded"
    ).toBeVisible({ timeout: resolveTimeout(120_000) });

    const accountSurface = page
      .locator(".o_action_manager")
      .getByText(/customer invoice|register payment|invoice date|tax excluded/i)
      .or(page.getByRole("button", { name: /^new$/i }))
      .or(page.locator(".o_breadcrumb, .o_control_panel").filter({ hasText: /invoic/i }))
      .first();
    await expect(
      accountSurface,
      "the Invoicing surface must expose account-domain content (a Customer Invoice / Register Payment / Invoice Date / Tax Excluded label, the New create button, or an Invoices breadcrumb) — present only because the account module installed and registered account.move views; a bare home shell does NOT satisfy this, distinguishing a real install from silent degradation"
    ).toBeVisible({ timeout: resolveTimeout(120_000) });

    await expect(
      page.locator(".o_action_manager"),
      "the loaded action must expose Accounting/Invoicing domain vocabulary (customer invoice / invoice / payment / tax / journal / bill), proving the account module — not a generic Odoo surface — is what rendered; if account is enabled but the module did not install, the route degrades to the home app and this text is absent, so the test MUST fail here"
    ).toContainText(/customer invoice|invoice|payment|tax excluded|journal|vendor bill/i, { timeout: resolveTimeout(120_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
