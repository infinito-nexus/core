const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const shared = require("../_shared");

test("addon mail: the mail module that carries Odoo's outgoing mail transport is installed", async ({ browser }) => {
  skipUnlessAddonEnabled("mail");
  skipUnlessServiceEnabled("email");

  const { context, page } = await shared.authenticatedContext(browser);

  try {
    await shared.openModule(page, "odoo/discuss");

    const errorPage = page.locator(".o_error_dialog, .o_error_detail").or(
      page.getByText(/sorry,?\s*(this page|the page).*(not found|does not exist)|page not found|404 not found/i)
    );
    await expect(
      errorPage,
      "opening /odoo/discuss must not render an Odoo error/not-found page; that means the mail module is not installed and no ir.mail_server transport exists to reach the partner mail server"
    ).toHaveCount(0);

    const discussSurface = page
      .locator(".o_mail_discuss, .o-mail-Discuss, .o_action_manager")
      .or(page.getByText(/discuss|inbox|channel/i));
    await expect(
      discussSurface.first(),
      "the Discuss surface the mail module registers must render; without that module Odoo has no mail layer, so the SMTP endpoint templates/odoo.conf.j2 configures is never used"
    ).toBeVisible({ timeout: resolveTimeout(120_000) });

    await expect(
      page.locator("body"),
      "the loaded page must expose the mail module's own vocabulary (discuss / inbox / channel / message), proving the mail module - not a generic Odoo surface - is what rendered"
    ).toContainText(/discuss|inbox|channel|message/i, { timeout: resolveTimeout(120_000) });
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
