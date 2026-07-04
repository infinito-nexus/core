const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { normalizeBaseUrl } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.CHECKMK_BASE_URL || process.env.APP_BASE_URL || "");

const FORGED_IDENTITY_HEADERS = {
  "X-Remote-User": "administrator",
  "X-Forwarded-User": "administrator",
  "X-Forwarded-Preferred-Username": "administrator",
};

test.use({ ignoreHTTPSErrors: true });

test("oidc-security: a forged X-Remote-User header cannot bypass the oauth2-proxy gate", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "CHECKMK_BASE_URL must be set").toBeTruthy();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: FORGED_IDENTITY_HEADERS,
  });
  try {
    const page = await context.newPage();
    await page.goto(`${expectedBase}/`, { waitUntil: "domcontentloaded" });

    await expect
      .poll(() => page.url(), {
        timeout: 60_000,
        message: "a forged X-Remote-User must be bounced to Keycloak, never into Checkmk",
      })
      .toContain("openid-connect/auth");

    const cookies = await context.cookies(expectedBase);
    expect(
      cookies.some((c) => c.name.startsWith("auth_")),
      "no Checkmk session cookie may be minted from a forged header",
    ).toBe(false);
  } finally {
    await context.close();
  }
});
