const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon communication_matrix: the Matrix communication provider is installed and listed among Moodle's plugins", async ({ page }) => {
  skipUnlessAddonEnabled("communication_matrix");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/plugins.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's plugin overview must list communication_matrix; the provider is absent when the " +
      "communication subsystem was stripped from the built Moodle source, so no course room can " +
      "be provisioned on the co-deployed Matrix homeserver",
  ).toContain("matrix");
});
