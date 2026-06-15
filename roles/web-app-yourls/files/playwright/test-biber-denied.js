const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { decodeDotenvQuotedValue, normalizeBaseUrl, performKeycloakLoginForm } = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.YOURLS_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const biberUsername = decodeDotenvQuotedValue(process.env.BIBER_USERNAME || "");
const biberPassword = decodeDotenvQuotedValue(process.env.BIBER_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

// biber is a regular authenticated Keycloak user but is NOT in the
// administrator group. YOURLS uses oauth2-proxy in ACL blacklist mode for
// /admin/, so oauth2-proxy must return HTTP 403 after biber completes the
// Keycloak login flow — the trusted-header bridge never runs for him.
test("yourls: biber is denied access to /admin/ after sso login", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "YOURLS_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
  expect(biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

  const base = baseUrl.replace(/\/$/, "");
  const expectedOidcAuthUrl = `${oidcIssuerUrl}/protocol/openid-connect/auth`;
  const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });

  try {
    const biberPage = await biberContext.newPage();

    const callbackResponsePromise = biberPage.waitForResponse(
      (res) => res.url().includes("/oauth2/callback"),
      { timeout: 60_000 },
    );

    await biberPage.goto(`${base}/admin/`);
    await expect
      .poll(() => biberPage.url(), {
        timeout: 30_000,
        message: `Expected redirect to Keycloak OIDC auth: ${expectedOidcAuthUrl}`,
      })
      .toContain(expectedOidcAuthUrl);

    await performKeycloakLoginForm(biberPage, biberUsername, biberPassword);

    const callbackResponse = await callbackResponsePromise;
    expect(
      callbackResponse.status(),
      `Expected oauth2-proxy to deny biber with 403 at /oauth2/callback, got ${callbackResponse.status()}`,
    ).toBe(403);
  } finally {
    await biberContext.close().catch(() => {});
  }
});
