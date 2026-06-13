const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.BOOKWYRM_BASE_URL || "");

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged identity header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "BOOKWYRM_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");

  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: { "X-Forwarded-Preferred-Username": "administrator" },
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/preferences/profile`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), { timeout: 60_000 })
      .toContain("openid-connect/auth");
    await expect(
      page.locator('form[name="edit-profile"]'),
      "a forged identity header must NOT yield an authenticated BookWyrm session",
    ).toHaveCount(0);
  } finally {
    await context.close();
  }
});
