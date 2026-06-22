const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon account: Accounting/Invoicing module is installed and its action loads", async ({ browser }) => {
  skipUnlessAddonEnabled("account");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    await shared.openModule(page, "odoo/accounting");

    const errorSurface = page.locator(".o_error_dialog, .o_action_manager .o_nocontent_help_error");
    await expect(
      errorSurface,
      "opening the Accounting action must not raise an Odoo error dialog; if 'account' is enabled but the module is not installed, the action route 404s/errors and this asserts the failure instead of passing on a bare web-client shell"
    ).toHaveCount(0);

    await expect(
      page.locator("body"),
      "the loaded page must expose Accounting domain vocabulary (Customer Invoices / Vendor Bills / Chart of Accounts / Journal Entries / Accounting), proving the account module — not a generic Odoo surface — is what rendered; if 'account' is enabled but the module did not install, /odoo/accounting degrades to the home shell and this text is absent, so the test MUST fail here"
    ).toContainText(/customer invoices|vendor bills|chart of accounts|journal entries|accounting/i, { timeout: 90_000 });

    const accountingSurface = page
      .locator(".o_account_dashboard")
      .or(page.locator(".o_control_panel, .o_breadcrumb").filter({ hasText: /accounting|invoic|bill|journal|chart of accounts/i }))
      .or(page.getByText(/customer invoices|vendor bills|chart of accounts|journal entries/i))
      .first();
    await expect(
      accountingSurface,
      "the Accounting action must render its own account-specific content surface (the accounting dashboard, or a control panel/breadcrumb naming Accounting/Invoices/Bills/Journals/Chart of Accounts, or account-domain text) — present only because the 'account' module installed and registered its views; a bare control panel/breadcrumb on the generic Odoo home shell does NOT satisfy this, distinguishing a working install from silent degradation"
    ).toBeVisible({ timeout: 90_000 });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
