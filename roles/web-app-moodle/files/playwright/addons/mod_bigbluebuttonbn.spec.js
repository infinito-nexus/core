const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon mod_bigbluebuttonbn: the BigBlueButton activity plugin is installed and listed among Moodle's plugins", async ({ page }) => {
  skipUnlessAddonEnabled("mod_bigbluebuttonbn");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = (process.env.APP_BASE_URL || "").replace(/\/$/, "");
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/plugins.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's plugin overview must list mod_bigbluebuttonbn; the component is absent when " +
      "the activity module was stripped from the built Moodle source, so no course can carry " +
      "a BigBlueButton room against the co-deployed partner",
  ).toContain("bigbluebuttonbn");
});
