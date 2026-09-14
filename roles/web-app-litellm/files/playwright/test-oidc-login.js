const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");
const {
  decodeDotenvQuotedValue,
  normalizeBaseUrl,
  performKeycloakLoginForm,
  gotoOnion,
} = require("./personas");

const baseUrl = normalizeBaseUrl(process.env.LITELLM_UI_BASE_URL || "");
const oidcIssuerUrl = normalizeBaseUrl(process.env.OIDC_ISSUER_URL || "");
const adminUsername = decodeDotenvQuotedValue(process.env.ADMIN_USERNAME || "");
const adminPassword = decodeDotenvQuotedValue(process.env.ADMIN_PASSWORD || "");

test.use({ ignoreHTTPSErrors: true });

test("OIDC: the LiteLLM admin UI signs the administrator in through Keycloak", async ({ page }) => {
  skipUnlessServiceEnabled("sso");
  expect(baseUrl, "LITELLM_UI_BASE_URL must be set").toBeTruthy();
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(adminUsername, "ADMIN_USERNAME must be set").toBeTruthy();
  expect(adminPassword, "ADMIN_PASSWORD must be set").toBeTruthy();
  await page.context().clearCookies();

  const expectedBase = baseUrl.replace(/\/$/, "");
  const expectedAuth = `${oidcIssuerUrl}/protocol/openid-connect/auth`;

  await gotoOnion(page, `${expectedBase}/sso/key/generate`);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(60_000),
      message: `expected /sso/key/generate to redirect to ${expectedAuth}; staying put means GENERIC_CLIENT_ID never reached the gateway`,
    })
    .toContain(expectedAuth);

  await performKeycloakLoginForm(page, adminUsername, adminPassword);

  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(90_000),
      message: `expected Keycloak to redirect back to ${expectedBase}`,
    })
    .toContain(expectedBase);

  await gotoOnion(page, `${expectedBase}/ui`, { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("input[type=password]"),
    "after the Keycloak round-trip the UI must not fall back to its own username/password gate",
  ).toHaveCount(0, { timeout: resolveTimeout(30_000) });
});
