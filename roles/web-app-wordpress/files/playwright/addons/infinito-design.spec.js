const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { gotoOnion } = require("../personas");
const { resolveTimeout } = require("../timeouts");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

test("addon infinito-design: the corporate design mu-plugin is loaded and registers its admin color scheme", async ({ page }) => {
  skipUnlessAddonEnabled("infinito-design");
  test.setTimeout(resolveTimeout(180_000));

  await shared.wpAdminLogin(page);
  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/plugins.php?plugin_status=mustuse`);
  await expect(
    page.locator("#the-list"),
    "the Must-Use plugins screen lists the mu-plugin under the Plugin Name its header declares",
  ).toContainText("Infinito.Nexus Corporate Design", { timeout: resolveTimeout(10_000) });

  await gotoOnion(page, `${shared.env.wpBaseUrl}/wp-admin/profile.php`);
  await expect(
    page.locator("#color-picker input[name='admin_color'][value='infinito']"),
    "the profile offers the corporate admin color scheme",
  ).toHaveCount(1, { timeout: resolveTimeout(10_000) });
});
