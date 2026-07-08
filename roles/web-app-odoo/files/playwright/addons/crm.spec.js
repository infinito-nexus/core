const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon crm: CRM module is installed and its pipeline feature renders", async ({ browser }) => {
  skipUnlessAddonEnabled("crm");
  test.setTimeout(resolveTimeout(180_000));

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.loginToOdoo(page);
    await shared.openModule(page, "odoo/crm");

    const errorPage = page.locator(".o_error_dialog, .o_error_detail").or(
      page.getByText(/sorry,?\s*(this page|the page).*(not found|does not exist)|page not found|404 not found/i)
    );
    await expect(
      errorPage,
      "opening /odoo/crm must not render an Odoo error/not-found page; that means the crm module is not installed"
    ).toHaveCount(0);

    const breadcrumb = page.locator(".o_breadcrumb, .o_control_panel, .breadcrumb");
    await expect(
      breadcrumb.first(),
      "the CRM action must render its own control panel — a bare web client navbar is not proof the crm module loaded"
    ).toBeVisible({ timeout: resolveTimeout(120_000) });

    const crmSurface = page
      .locator(".o_crm_lead_kanban, .o_kanban_view")
      .or(page.getByRole("button", { name: /^new$/i }))
      .or(page.getByText(/pipeline/i))
      .or(breadcrumb.filter({ hasText: /crm|pipeline|lead|opportunit/i }));
    await expect(
      crmSurface.first(),
      "the CRM pipeline surface (lead/opportunity kanban, the New button, or a CRM/Pipeline control-panel label) must render when the crm addon is enabled; its absence means the module did not install — fail, do not skip"
    ).toBeVisible({ timeout: resolveTimeout(120_000) });

    await expect(
      page.locator("body"),
      "the loaded page must expose CRM domain vocabulary (CRM / pipeline / lead / opportunity), proving the crm module — not a generic Odoo surface — is what rendered"
    ).toContainText(/crm|pipeline|lead|opportunit/i, { timeout: resolveTimeout(120_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
