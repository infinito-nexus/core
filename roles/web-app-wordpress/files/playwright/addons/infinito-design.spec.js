const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceDisabled, skipUnlessServiceEnabled } = require("../service-gating");
const { gotoOnion } = require("../personas");
const { resolveTimeout } = require("../timeouts");
const shared = require("../_shared");

test.use({ ignoreHTTPSErrors: true });

const MUST_USE_SCREEN = "/wp-admin/plugins.php?plugin_status=mustuse";
const PROFILE_SCREEN = "/wp-admin/profile.php";
const PLUGIN_NAME = "Infinito.Nexus Corporate Design";
const ANY_SCHEME = "#color-picker input[name='admin_color']";
const CORPORATE_SCHEME = "#color-picker input[name='admin_color'][value='infinito']";

async function openMustUseScreen(page) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}${MUST_USE_SCREEN}`);
  await expect(
    page.locator("#the-list"),
    "the Must-Use plugins screen lists the mu-plugin under the Plugin Name its header declares",
  ).toContainText(PLUGIN_NAME, { timeout: resolveTimeout(10_000) });
}

async function openProfileScreen(page) {
  await gotoOnion(page, `${shared.env.wpBaseUrl}${PROFILE_SCREEN}`);
  await expect(
    page.locator(ANY_SCHEME).first(),
    "profile.php must render WordPress's own admin color schemes, otherwise a missing corporate entry only proves the picker never loaded",
  ).toBeAttached({ timeout: resolveTimeout(10_000) });
}

test("addon infinito-design: the corporate design mu-plugin is loaded and registers its admin color scheme", async ({ page }) => {
  skipUnlessAddonEnabled("infinito-design");
  skipUnlessServiceEnabled("design");
  test.setTimeout(resolveTimeout(180_000));

  await shared.wpAdminLogin(page);
  await openMustUseScreen(page);

  await openProfileScreen(page);
  await expect(
    page.locator(CORPORATE_SCHEME),
    "the profile offers the corporate admin color scheme",
  ).toHaveCount(1, { timeout: resolveTimeout(10_000) });
});

test("addon infinito-design: the mu-plugin stays installed and registers no admin color scheme while the design service is off", async ({ page }) => {
  skipUnlessAddonEnabled("infinito-design");
  skipUnlessServiceDisabled("design");
  test.setTimeout(resolveTimeout(180_000));

  await shared.wpAdminLogin(page);
  await openMustUseScreen(page);

  await openProfileScreen(page);
  await expect(
    page.locator(CORPORATE_SCHEME),
    "08_design.yml withdrew the design, so files/php/design.php deleted the infinito_design option and the mu-plugin must register no corporate admin color scheme",
  ).toHaveCount(0, { timeout: resolveTimeout(10_000) });
});
