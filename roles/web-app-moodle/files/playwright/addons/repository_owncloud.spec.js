const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon repository_owncloud: the Nextcloud repository plugin is installed and listed among Moodle's repositories", async ({ page }) => {
  skipUnlessAddonEnabled("repository_owncloud");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/repository.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's repository administration must offer the ownCloud/Nextcloud repository type; it is " +
      "absent when the repository plugin was stripped from the built Moodle source, so no course " +
      "file picker can reach the co-deployed Nextcloud partner",
  ).toMatch(/owncloud|nextcloud/i);
});
