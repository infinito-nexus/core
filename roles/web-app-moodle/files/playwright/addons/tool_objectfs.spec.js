const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { skipUnlessServiceEnabled } = require("../service-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon tool_objectfs: the plugin is installed and listed among Moodle's plugins", async ({ page }) => {
  skipUnlessAddonEnabled("tool_objectfs");
  skipUnlessServiceEnabled("seaweedfs");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/plugins.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's plugin overview must list tool_objectfs; the component is absent when " +
      "tasks/utils/objectfs.yml did not reach upgrade.php, so the plugin directory sits in " +
      "the code volume without its tables",
  ).toContain("tool_objectfs");
});
