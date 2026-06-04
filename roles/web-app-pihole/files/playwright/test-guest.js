// @ts-check
// Scenario: Unauthenticated guest is redirected to SSO login
const { test, expect } = require("@playwright/test");

test.use({ ignoreHTTPSErrors: true });

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) return value;
  if (!(value.startsWith('"') && value.endsWith('"'))) return value;
  const encoded = value.slice(1, -1);
  try { return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$"); }
  catch { return encoded.replace(/\$\$/g, "$"); }
}

const oidcIssuerUrl = decodeDotenvQuotedValue(process.env.OIDC_ISSUER_URL);
const piholeBaseUrl = decodeDotenvQuotedValue(process.env.PIHOLE_BASE_URL);

test.beforeEach(() => {
  expect(oidcIssuerUrl, "OIDC_ISSUER_URL must be set").toBeTruthy();
  expect(piholeBaseUrl, "PIHOLE_BASE_URL must be set").toBeTruthy();
});

test("guest: is redirected to SSO login", async ({ page }) => {
  const expectedOidcAuthUrl = `${oidcIssuerUrl.replace(/\/$/, "")}/protocol/openid-connect/auth`;
  await page.goto(`${piholeBaseUrl.replace(/\/$/, "")}/`);
  await expect
    .poll(() => page.url(), { timeout: 30_000, message: "Expected redirect to Keycloak OIDC auth" })
    .toContain(expectedOidcAuthUrl);
});
