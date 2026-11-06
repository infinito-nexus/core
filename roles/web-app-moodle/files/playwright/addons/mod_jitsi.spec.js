const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon mod_jitsi: the Jitsi activity plugin is installed and listed among Moodle's plugins", async ({ page }) => {
  skipUnlessAddonEnabled("mod_jitsi");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/plugins.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's plugin overview must list mod_jitsi; the component is absent when the image " +
      "build never unpacked the plugin into mod/jitsi, so the plugin directory carries no " +
      "tables and no course can open a room on the co-deployed Jitsi partner",
  ).toContain("jitsi");
});
