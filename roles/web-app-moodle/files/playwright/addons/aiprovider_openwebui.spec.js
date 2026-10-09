const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const { loginAsSiteAdmin } = require("../_shared");
const { gotoOnion, normalizeBaseUrl } = require("../personas");

test.use({ ignoreHTTPSErrors: true });

test("addon aiprovider_openwebui: the Open WebUI AI provider is installed and listed among Moodle's plugins", async ({ page }) => {
  skipUnlessAddonEnabled("aiprovider_openwebui");
  test.setTimeout(resolveTimeout(180_000));

  const appBaseUrl = normalizeBaseUrl(process.env.APP_BASE_URL);
  test.skip(!appBaseUrl, "APP_BASE_URL not set for this role");

  await loginAsSiteAdmin(page);

  await gotoOnion(page, `${appBaseUrl}/admin/plugins.php`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});

  const body = (await page.locator("body").innerText().catch(() => "")) || "";
  expect(
    body,
    "Moodle's plugin overview must list aiprovider_openwebui; the component is absent when the " +
      "image build never unpacked it into ai/provider/openwebui, so the AI subsystem has no " +
      "provider pointing at the co-deployed Open WebUI partner",
  ).toContain("openwebui");
});
